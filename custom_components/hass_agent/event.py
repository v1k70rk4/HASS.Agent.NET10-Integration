"""Event platform for HASS.Agent notification actions."""

from __future__ import annotations

import json
import logging
from typing import Any, ClassVar

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.mqtt.subscription import (
    async_prepare_subscribe_topics,
    async_subscribe_topics,
    async_unsubscribe_topics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ACTION,
    CONF_DEVICE_NAME,
    CONF_ORIGINAL_DEVICE_NAME,
    DOMAIN,
    EVENT_NOTIFICATION_ACTIONS,
)
from .entity import HassAgentAvailableEntity

_LOGGER = logging.getLogger(__name__)

EVENT_TYPE_ACTION = "action"
# What the integration fires on the bus for a press. Deliberately not "hass_agent_hotkey":
# that is the client's own WebSocket event, which __init__ listens to; the same name here
# would feed every press straight back into that listener.
EVENT_HOTKEY_PRESSED = "hass_agent_hotkey_pressed"


def own_device(event_data: dict[str, Any], device_name: str, serial_number: str | None) -> None:
    """Name the device the event came in for, whatever the payload says.

    Automations match these events on the device name. A PC, or anything else that can
    publish to the broker, must not be able to fire them in another PC's name.
    """
    event_data[CONF_DEVICE_NAME] = device_name
    event_data["serial_number"] = serial_number


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HASS.Agent event entities from a config entry."""
    device_name = entry.data.get("device", {}).get("name", entry.title)
    original_device_name = entry.data.get(CONF_ORIGINAL_DEVICE_NAME, device_name)

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    apis = entry_data.get("apis", {})
    if not isinstance(apis, dict):
        apis = {}

    entities: list[EventEntity] = []
    # Every client sends the notifications flag; a payload without it is treated as before
    # (the entity existed whenever the platform was loaded).
    if apis.get("notifications") is not False:
        entities.append(HassAgentNotificationActionEventEntity(entry, device_name, original_device_name))

    hotkeys = apis.get("hotkeys")
    if isinstance(hotkeys, list) and hotkeys:
        entities.append(HassAgentHotkeyEventEntity(entry, device_name, hotkeys))

    async_add_entities(entities)


class HassAgentNotificationActionEventEntity(HassAgentAvailableEntity, EventEntity):
    """HASS.Agent notification action event entity."""

    _attr_event_types: ClassVar[list[str]] = [EVENT_TYPE_ACTION]
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_has_entity_name = True
    _attr_translation_key = "notification_action"

    def __init__(
        self,
        entry: ConfigEntry,
        device_name: str,
        original_device_name: str,
    ) -> None:
        """Initialize the notification action event entity."""
        self._entry = entry
        self._device_name = device_name
        self._topic_id = entry.unique_id
        self._original_device_name = original_device_name
        self._attr_unique_id = f"event_{entry.unique_id}_notification_action"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
        )
        self._listeners: dict[str, Any] = {}
        self._setup_availability(entry.entry_id)

    @callback
    def _own_device(self, event_data: dict[str, Any]) -> None:
        own_device(event_data, self._device_name, self._topic_id)

    def _provider_online(self, entry_data: dict) -> bool | None:
        """Notifications come from the tray app, so this follows the tray app alone."""
        return self._app_online(entry_data)

    @callback
    def _handle_action_message(self, message: ReceiveMessage) -> None:
        """Handle a notification action MQTT message."""
        if not message.payload:
            _LOGGER.debug("received empty notification action on '%s', ignoring", message.topic)
            return

        try:
            payload = json.loads(message.payload)
        except ValueError:
            _LOGGER.warning("received invalid notification action JSON on '%s'", message.topic)
            return

        if not isinstance(payload, dict):
            _LOGGER.warning("received non-object notification action on '%s'", message.topic)
            return

        action = payload.get(CONF_ACTION)
        if not isinstance(action, str) or not action:
            _LOGGER.warning("received notification action without action value on '%s'", message.topic)
            return

        event_data = dict(payload)
        event_data[CONF_ACTION] = action
        self._own_device(event_data)

        self.hass.bus.async_fire(EVENT_NOTIFICATION_ACTIONS, event_data)
        self._trigger_event(EVENT_TYPE_ACTION, event_data)
        self.async_write_ha_state()

    @callback
    def _handle_ws_notification_action(self, data: Any) -> None:
        """Handle a notification action received via WebSocket transport."""
        if not isinstance(data, dict):
            return

        action = data.get(CONF_ACTION)
        if not isinstance(action, str) or not action:
            return

        event_data = dict(data)
        self._own_device(event_data)

        self.hass.bus.async_fire(EVENT_NOTIFICATION_ACTIONS, event_data)
        self._trigger_event(EVENT_TYPE_ACTION, event_data)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to notification action messages."""
        if not self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("ha_api_only", False):
            self._listeners = async_prepare_subscribe_topics(
                self.hass,
                self._listeners,
                {
                    f"{self._attr_unique_id}-actions": {
                        "topic": f"hass.agent/notifications/{self._topic_id}/actions",
                        "msg_callback": self._handle_action_message,
                        "qos": 0,
                    }
                },
            )

            await async_subscribe_topics(self.hass, self._listeners)

        # Also listen for notification actions coming via WebSocket transport.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"hass_agent_notification_action_{self._entry.entry_id}",
                self._handle_ws_notification_action,
            )
        )

        await self._connect_availability()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from notification action messages."""
        if self._listeners:
            async_unsubscribe_topics(self.hass, self._listeners)
            self._listeners = {}


class HassAgentHotkeyEventEntity(HassAgentAvailableEntity, EventEntity):
    """The hotkeys of the tray app (client 10.9.0+): one event type per hotkey name.

    Pressing a listed combination on the PC fires the event with the hotkey's name as
    the type, so an automation can trigger on it. The types come from what the client
    advertises; a name that arrives unannounced is added on the spot.
    """

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_has_entity_name = True
    _attr_translation_key = "hotkey"
    _attr_icon = "mdi:keyboard"

    def __init__(self, entry: ConfigEntry, device_name: str, hotkeys: list[Any]) -> None:
        """Initialize the hotkey event entity."""
        self._entry = entry
        self._device_name = device_name
        self._topic_id = entry.unique_id
        self._attr_unique_id = f"event_{entry.unique_id}_hotkey"
        self._attr_event_types = self._names(hotkeys)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)})
        self._listeners: dict[str, Any] = {}
        self._setup_availability(entry.entry_id)

    @staticmethod
    def _names(hotkeys: list[Any]) -> list[str]:
        names: list[str] = []
        for hotkey in hotkeys:
            name = hotkey.get("name") if isinstance(hotkey, dict) else None
            if isinstance(name, str) and name and name not in names:
                names.append(name)
        return names

    def _provider_online(self, entry_data: dict) -> bool | None:
        """Hotkeys are the tray app's; this follows the tray app alone."""
        return self._app_online(entry_data)

    @callback
    def _fire(self, data: dict[str, Any]) -> None:
        name = data.get("hotkey")
        if not isinstance(name, str) or not name:
            return

        if name not in self._attr_event_types:
            self._attr_event_types = [*self._attr_event_types, name]

        event_data = dict(data)
        own_device(event_data, self._device_name, self._topic_id)
        self.hass.bus.async_fire(EVENT_HOTKEY_PRESSED, event_data)
        self._trigger_event(name, event_data)
        self.async_write_ha_state()

    @callback
    def _handle_mqtt(self, message: ReceiveMessage) -> None:
        if not message.payload:
            return
        try:
            payload = json.loads(message.payload)
        except ValueError:
            _LOGGER.warning("received invalid hotkey JSON on '%s'", message.topic)
            return
        if isinstance(payload, dict):
            self._fire(payload)

    @callback
    def _handle_ws(self, data: Any) -> None:
        if isinstance(data, dict):
            self._fire(data)

    async def async_added_to_hass(self) -> None:
        """Subscribe to hotkey presses on both transports."""
        if not self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("ha_api_only", False):
            self._listeners = async_prepare_subscribe_topics(
                self.hass,
                self._listeners,
                {
                    f"{self._attr_unique_id}-pressed": {
                        "topic": f"hass.agent/hotkeys/{self._topic_id}/pressed",
                        "msg_callback": self._handle_mqtt,
                        "qos": 0,
                    }
                },
            )
            await async_subscribe_topics(self.hass, self._listeners)

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"hass_agent_hotkey_{self._entry.entry_id}",
                self._handle_ws,
            )
        )
        await self._connect_availability()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from hotkey presses."""
        if self._listeners:
            async_unsubscribe_topics(self.hass, self._listeners)
            self._listeners = {}
