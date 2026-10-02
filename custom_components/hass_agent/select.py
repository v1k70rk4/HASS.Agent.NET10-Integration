"""Select platform for HASS.Agent: the default audio output and input device."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.mqtt.subscription import (
    async_prepare_subscribe_topics,
    async_subscribe_topics,
    async_unsubscribe_topics,
)
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import HassAgentAvailableEntity, async_get_agent_device

_LOGGER = logging.getLogger(__name__)

# (sensor key the client advertises, key of the device list in the payload, command, translation key, icon)
AUDIO_SELECTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("audio_output_device", "audio_output_devices", "set_audio_output", "audio_output", "mdi:speaker"),
    ("audio_input_device", "audio_input_devices", "set_audio_input", "audio_input", "mdi:microphone"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the audio device selects the client advertises a sensor for."""
    device = async_get_agent_device(hass, entry)
    if device is None:
        return False

    signature = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("standard_sensors", ())
    advertised = {
        item[0]
        for item in signature
        if isinstance(item, (tuple, list)) and len(item) == 2
    }

    async_add_entities(
        HassAgentAudioSelect(entry.entry_id, entry.unique_id, device, *definition)
        for definition in AUDIO_SELECTS
        if definition[0] in advertised
    )
    return True


class HassAgentAudioSelect(HassAgentAvailableEntity, SelectEntity):
    """Chooses the default playback or recording device of the PC.

    The client (10.9.0+, tray app) sends the current device and the list of devices that
    can be chosen with its sensor data. An older client sends no list; the select then
    stays unavailable and the plain sensor keeps showing the device.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        unique_id: str,
        device: dr.DeviceEntry,
        current_key: str,
        list_key: str,
        command: str,
        translation_key: str,
        icon: str,
    ) -> None:
        """Initialize the select."""
        self._entry_id = entry_id
        self._serial_number = unique_id
        self._current_key = current_key
        self._list_key = list_key
        self._command = command
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_unique_id = f"select_{unique_id}_{translation_key}"
        self._attr_device_info = DeviceInfo(
            identifiers=device.identifiers,
            name=device.name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
        )
        self._attr_options = []
        self._attr_current_option = None
        self._has_list = False
        self._listeners: dict[str, Any] = {}
        self._setup_availability(entry_id)

    def _provider_online(self, entry_data: dict) -> bool | None:
        """The tray app feeds this; the service has no audio session."""
        return self._app_online(entry_data)

    @property
    def available(self) -> bool:
        """Available once the tray app is up and has sent the device list."""
        return bool(self._attr_available) and self._has_list

    @callback
    def _apply(self, payload: Any) -> None:
        """Take the device list and the current device out of a sensor payload."""
        if not isinstance(payload, dict):
            return

        devices = payload.get(self._list_key)
        if not isinstance(devices, list):
            return

        options = [name for name in devices if isinstance(name, str) and name]
        current = payload.get(self._current_key)
        if not isinstance(current, str) or not current:
            current = None
        elif current not in options:
            # The state is cut to 255 characters; the list is not.
            current = next((name for name in options if name.startswith(current)), None)

        self._attr_options = options
        self._attr_current_option = current
        self._has_list = True
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

    async def async_select_option(self, option: str) -> None:
        """Ask the tray app to make this device the default."""
        payload = {"command": self._command, "text": option}

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
                _LOGGER.debug("audio device command not sent over MQTT: %s", err)

        self.hass.bus.async_fire("hass_agent_command", {
            "serial_number": self._serial_number,
            "command_type": "button_command",
            "target": "app",
            "payload": payload,
        })

        # Shown at once; the client confirms (or corrects) it with its next sensor data.
        self._attr_current_option = option
        self.async_write_ha_state()
