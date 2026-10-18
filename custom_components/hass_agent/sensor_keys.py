"""Sensor keys the Windows client renamed, read under their current name.

The client 10.9.3 dropped the unit from two keys once their attributes came in other
units (system_drive_free_gb.total_gb read oddly). An older client still sends the old
key; a newer one sends both for a while, for an integration from before. Either way the
entity lives under the new key here, and the one made under the old key is moved over
once, with its entity ID, its history and its statistics.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

RENAMED_SENSOR_KEYS: dict[str, str] = {
    "system_drive_free_gb": "system_drive",
    "memory_available_mb": "memory_available",
}


def current_sensor_key(key: str) -> str:
    """The key as the client names it today."""
    return RENAMED_SENSOR_KEYS.get(key, key)


def with_current_sensor_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """The metrics payload with every renamed key under its current name.

    The value and the sensor's attributes both; when the client sends both names the
    current one wins. A payload without any old key comes back as it is.
    """
    if not any(old in payload for old in RENAMED_SENSOR_KEYS):
        attributes = payload.get("attributes")
        if not isinstance(attributes, dict) or not any(old in attributes for old in RENAMED_SENSOR_KEYS):
            return payload

    result = dict(payload)
    for old, new in RENAMED_SENSOR_KEYS.items():
        if old in result:
            value = result.pop(old)
            result.setdefault(new, value)

    attributes = result.get("attributes")
    if isinstance(attributes, dict):
        attributes = dict(attributes)
        for old, new in RENAMED_SENSOR_KEYS.items():
            if old in attributes:
                value = attributes.pop(old)
                attributes.setdefault(new, value)
        result["attributes"] = attributes

    return result


@callback
def async_migrate_renamed_sensor_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move an entity made under an old key to the new one, keeping its entity ID.

    When the new key already has an entity of its own, the old one is removed instead:
    two entities for one value would be left over from a client that sent both.
    """
    registry = er.async_get(hass)
    for old, new in RENAMED_SENSOR_KEYS.items():
        old_entity_id = registry.async_get_entity_id(Platform.SENSOR.value, DOMAIN, f"sensor_{entry.unique_id}_{old}")
        if old_entity_id is None:
            continue

        new_unique_id = f"sensor_{entry.unique_id}_{new}"
        if registry.async_get_entity_id(Platform.SENSOR.value, DOMAIN, new_unique_id) is not None:
            registry.async_remove(old_entity_id)
            continue

        registry.async_update_entity(old_entity_id, new_unique_id=new_unique_id)
