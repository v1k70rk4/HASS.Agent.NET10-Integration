"""Provides device triggers for HASS.Agent."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.components.mqtt.const import (
    CONF_ENCODING,
    CONF_PAYLOAD,
    CONF_QOS,
    CONF_TOPIC,
)
from homeassistant.components.mqtt.device_trigger import DEFAULT_ENCODING, mqtt_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_EVENT,
    CONF_PLATFORM,
    CONF_TYPE,
    CONF_VALUE_TEMPLATE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import (
    TriggerActionType,
    TriggerInfo,
)
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ACTION,
    CONF_MEDIA_PLAYER_POWER,
    DOMAIN,
    EVENT_NOTIFICATION_ACTIONS,
    EVENT_TURN_OFF_REQUESTED,
    EVENT_TURN_ON_REQUESTED,
)

NOTIFICATION_TRIGGER_TYPES = {"notifications_mqtt", "notifications_event"}
# The media player's turn on or turn off was called: an automation wakes the PC (Wake on
# LAN, a smart plug, ...) or does whatever else belongs to turning it off. Offered when
# power control is on in the options.
POWER_TRIGGER_EVENTS = {
    "turn_on": EVENT_TURN_ON_REQUESTED,
    "turn_off": EVENT_TURN_OFF_REQUESTED,
}

TRIGGER_SCHEMA = vol.Any(
    DEVICE_TRIGGER_BASE_SCHEMA.extend(
        {vol.Required(CONF_TYPE): vol.In(NOTIFICATION_TRIGGER_TYPES), vol.Required(CONF_ACTION): str}
    ),
    DEVICE_TRIGGER_BASE_SCHEMA.extend({vol.Required(CONF_TYPE): vol.In(POWER_TRIGGER_EVENTS)}),
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """List device triggers for HASS.Agent devices."""

    types = sorted(NOTIFICATION_TRIGGER_TYPES)
    if _power_control_on(hass, device_id):
        types.extend(POWER_TRIGGER_EVENTS)

    triggers = [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: t,
        }
        for t in types
    ]

    return triggers


def _power_control_on(hass: HomeAssistant, device_id: str) -> bool:
    """Whether the media player power option is on for this device's entry."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return False

    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN and entry.options.get(CONF_MEDIA_PLAYER_POWER, False):
            return True
    return False


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger."""

    device_registry = dr.async_get(hass)

    device = device_registry.async_get(config[CONF_DEVICE_ID])

    if device is None:
        return None

    device_name = device.name
    topic_id = next(
        (identifier for domain, identifier in device.identifiers if domain == DOMAIN),
        device_name,
    )

    if config[CONF_TYPE] in POWER_TRIGGER_EVENTS:
        power_config = event_trigger.TRIGGER_SCHEMA(
            {
                event_trigger.CONF_PLATFORM: CONF_EVENT,
                event_trigger.CONF_EVENT_TYPE: POWER_TRIGGER_EVENTS[config[CONF_TYPE]],
                event_trigger.CONF_EVENT_DATA: {"serial_number": topic_id},
            }
        )
        return await event_trigger.async_attach_trigger(
            hass, power_config, action, trigger_info, platform_type="device"
        )

    if config[CONF_TYPE] == "notifications_mqtt":
        mqtt_config = {
            CONF_PLATFORM: "mqtt",
            CONF_TOPIC: f"hass.agent/notifications/{topic_id}/actions",
            CONF_ENCODING: DEFAULT_ENCODING,
            CONF_QOS: 0,
            CONF_PAYLOAD: config[CONF_ACTION],
            CONF_VALUE_TEMPLATE: "{{ value_json.action }}",
        }

        mqtt_config = mqtt_trigger.TRIGGER_SCHEMA(mqtt_config)

        return await mqtt_trigger.async_attach_trigger(
            hass,
            mqtt_config,
            action,
            trigger_info,
        )

    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: CONF_EVENT,
            event_trigger.CONF_EVENT_TYPE: EVENT_NOTIFICATION_ACTIONS,
            # By serial number, which a PC cannot change, rather than by its name.
            event_trigger.CONF_EVENT_DATA: {
                "serial_number": topic_id,
                CONF_ACTION: config[CONF_ACTION],
            },
        }
    )

    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """List trigger capabilities."""
    if config.get(CONF_TYPE) in POWER_TRIGGER_EVENTS:
        return {}
    return {"extra_fields": vol.Schema({vol.Required(CONF_ACTION): str})}
