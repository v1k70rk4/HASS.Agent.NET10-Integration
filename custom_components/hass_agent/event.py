"""Event platform for HASS.Agent notification actions."""

from __future__ import annotations

import json
import logging
from typing import Any

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HASS.Agent event entities from a config entry."""
    device_name = entry.data.get("device", {}).get("name", entry.title)
    original_device_name = entry.data.get(CONF_ORIGINAL_DEVICE_NAME, device_name)

    async_add_entities(
        [
            HassAgentNotificationActionEventEntity(
                entry,
                device_name,
                original_device_name,
            )
        ]
    )


class HassAgentNotificationActionEventEntity(HassAgentAvailableEntity, EventEntity):
    """HASS.Agent notification action event entity."""

    _attr_event_types = [EVENT_TYPE_ACTION]
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
        event_data.setdefault(CONF_DEVICE_NAME, self._device_name)

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
        event_data.setdefault(CONF_DEVICE_NAME, self._device_name)

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
