"""Light platform for HASS.Agent: the PC's display, with its brightness."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.mqtt.subscription import (
    async_prepare_subscribe_topics,
    async_subscribe_topics,
    async_unsubscribe_topics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import HassAgentAvailableEntity, async_get_agent_device

# The agent reports this key when its "Display brightness" sensor is enabled (agent
# 10.9.0+, tray app). The light is built from it rather than a plain sensor.
BRIGHTNESS_KEY = "display_brightness"
MONITOR_POWER_KEY = "monitor_power_state"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the display light when the agent advertises its brightness."""
    device = async_get_agent_device(hass, entry)
    if device is None:
        return False

    signature = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("standard_sensors", ())
    advertised = any(
        isinstance(item, (tuple, list)) and len(item) == 2 and item[0] == BRIGHTNESS_KEY
        for item in signature
    )
    if advertised:
        async_add_entities([HassAgentDisplayLight(entry.entry_id, entry.unique_id, device)])

    return True


class HassAgentDisplayLight(HassAgentAvailableEntity, LightEntity):
    """The display of the PC: brightness, and on/off through the monitor power.

    The agent sets every display it can adjust (a laptop's panel, DDC/CI monitors)
    and reports the brightness of the first one. With no adjustable display it reports
    nothing, and the light stays unavailable.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "display"
    _attr_icon = "mdi:monitor"
    _attr_should_poll = False
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, entry_id: str, unique_id: str, device: dr.DeviceEntry) -> None:
        """Initialize the light."""
        self._entry_id = entry_id
        self._serial_number = unique_id
        self._attr_unique_id = f"light_{unique_id}_display"
        self._attr_device_info = DeviceInfo(
            identifiers=device.identifiers,
            name=device.name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
        )
        self._percent: int | None = None
        self._monitor_on = True
        self._listeners: dict[str, Any] = {}
        self._setup_availability(entry_id)

    def _provider_online(self, entry_data: dict) -> bool | None:
        """The tray app feeds this; the service has no desktop."""
        return self._app_online(entry_data)

    @property
    def available(self) -> bool:
        """Available once the tray app is up and has reported a brightness."""
        return bool(self._attr_available) and self._percent is not None

    @property
    def is_on(self) -> bool | None:
        """On while the monitor is powered."""
        return self._monitor_on

    @property
    def brightness(self) -> int | None:
        """Brightness on Home Assistant's 0..255 scale."""
        if self._percent is None:
            return None
        return max(1, round(self._percent * 255 / 100)) if self._percent > 0 else 0

    @callback
    def _apply(self, payload: Any) -> None:
        """Take the brightness and the monitor power out of a sensor payload."""
        if not isinstance(payload, dict):
            return

        changed = False
        value = payload.get(BRIGHTNESS_KEY)
        if isinstance(value, int | float) and not isinstance(value, bool):
            self._percent = max(0, min(100, round(value)))
            changed = True

        power = payload.get(MONITOR_POWER_KEY)
        if isinstance(power, str):
            self._monitor_on = power != "off"
            changed = True

        if changed:
            self.async_write_ha_state()

    @callback
    def _updated(self, message: ReceiveMessage) -> None:
        """Handle the shared sensor state topic."""
        if not message.payload:
            return
        try:
            self._apply(json.loads(message.payload))
        except ValueError:
            return

    async def async_added_to_hass(self) -> None:
        """Subscribe to the sensor state on both transports."""
        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("ha_api_only", False):
            self._listeners = async_prepare_subscribe_topics(
                self.hass,
                self._listeners,
                {
                    f"{self._attr_unique_id}-state": {
                        "topic": f"hass.agent/sensors/{self._serial_number}/state",
                        "msg_callback": self._updated,
                        "qos": 0,
                    }
                },
            )
            await async_subscribe_topics(self.hass, self._listeners)

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"hass_agent_sensor_data_{self._entry_id}",
                self._apply,
            )
        )
        await self._connect_availability()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from the sensor state."""
        if self._listeners:
            async_unsubscribe_topics(self.hass, self._listeners)
            self._listeners = {}

    async def _send(self, payload: dict[str, object]) -> None:
        """Send a display command to the tray app, on whichever transport is in use."""
        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("ha_api_only", False):
            await mqtt.async_publish(
                self.hass,
                f"hass.agent/buttons/{self._serial_number}/cmd",
                json.dumps(payload),
                qos=0,
                retain=False,
            )

        self.hass.bus.async_fire("hass_agent_command", {
            "serial_number": self._serial_number,
            "command_type": "button_command",
            "target": "app",
            "payload": payload,
        })

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Wake the display, and set the brightness when one is given."""
        payload: dict[str, object] = {"command": "set_brightness" if self._monitor_on else "display_on"}
        if ATTR_BRIGHTNESS in kwargs:
            percent = max(0, min(100, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)))
            payload["value"] = percent
            self._percent = percent
        elif self._monitor_on:
            # Already on and nothing to change.
            return

        self._monitor_on = True
        await self._send(payload)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the monitor off; the brightness is kept for when it comes back."""
        self._monitor_on = False
        await self._send({"command": "display_off"})
        self.async_write_ha_state()
