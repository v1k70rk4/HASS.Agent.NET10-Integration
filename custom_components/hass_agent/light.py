"""Light platform for HASS.Agent: the PC's display, with its brightness."""

from __future__ import annotations

import json
import logging
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import HassAgentAvailableEntity, async_get_agent_device

# The agent reports this key when its "Display brightness" sensor is enabled (agent
# 10.9.0+, tray app). The light is built from it rather than a plain sensor.
_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_KEY = "display_brightness"
SUPPORTED_KEY = "display_brightness_supported"
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
    and reports the brightness of the first one. With no adjustable display (many TVs)
    it says so, and the light is a plain on/off one.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "display"
    _attr_icon = "mdi:monitor"
    _attr_should_poll = False

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
        # None until the agent has reported: whether a brightness can be read and set.
        self._dimmable: bool | None = None
        # Optimistic until the monitor power sensor (if enabled) says otherwise; None when
        # that sensor reports a state it cannot tell.
        self._monitor_on: bool | None = True
        self._listeners: dict[str, Any] = {}
        self._setup_availability(entry_id)

    def _provider_online(self, entry_data: dict) -> bool | None:
        """The tray app feeds this; the service has no desktop."""
        return self._app_online(entry_data)

    @property
    def available(self) -> bool:
        """Available once the tray app is up and has reported what the display can do."""
        return bool(self._attr_available) and self._dimmable is not None

    @property
    def color_mode(self) -> ColorMode:
        """Brightness when the display can be dimmed, plain on/off otherwise."""
        return ColorMode.BRIGHTNESS if self._dimmable else ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Follows what the agent reports about the display."""
        return {self.color_mode}

    @property
    def is_on(self) -> bool | None:
        """On while the monitor is powered; unknown when the client cannot tell."""
        return self._monitor_on

    @property
    def brightness(self) -> int | None:
        """Brightness on Home Assistant's 0..255 scale."""
        if not self._dimmable or self._percent is None:
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
            self._dimmable = True
            changed = True
        elif payload.get(SUPPORTED_KEY) is False:
            # The sensor is on, but no display there can be adjusted.
            self._percent = None
            self._dimmable = False
            changed = True

        power = payload.get(MONITOR_POWER_KEY)
        if isinstance(power, str):
            # "dimmed" is still on; anything else ("unknown") is not known to be either.
            self._monitor_on = True if power in ("on", "dimmed") else False if power == "off" else None
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
            try:
                await mqtt.async_publish(
                    self.hass,
                    f"hass.agent/buttons/{self._serial_number}/cmd",
                    json.dumps(payload),
                    qos=0,
                    retain=False,
                )
            except HomeAssistantError as err:
                # The broker being away must not keep the command from the HA API transport.
                _LOGGER.debug("display command not sent over MQTT: %s", err)

        self.hass.bus.async_fire("hass_agent_command", {
            "serial_number": self._serial_number,
            "command_type": "button_command",
            "target": "app",
            "payload": payload,
        })

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Wake the display, and set the brightness when one is given."""
        # Wake the display unless it is known to be on.
        payload: dict[str, object] = {"command": "set_brightness" if self._monitor_on is True else "display_on"}
        if ATTR_BRIGHTNESS in kwargs and self._dimmable:
            percent = max(0, min(100, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)))
            payload["value"] = percent
            self._percent = percent
        elif self._monitor_on is True:
            # Known to be on and nothing to change.
            return

        self._monitor_on = True
        await self._send(payload)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the monitor off; the brightness is kept for when it comes back."""
        self._monitor_on = False
        await self._send({"command": "display_off"})
        self.async_write_ha_state()
