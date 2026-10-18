"""The two sensor keys the client renamed: read under the new name, entity moved over."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hass_agent import _normalize_standard_sensors
from custom_components.hass_agent.const import DOMAIN
from custom_components.hass_agent.sensor_keys import (
    async_migrate_renamed_sensor_entities,
    current_sensor_key,
    with_current_sensor_keys,
)

SERIAL = "0123456789abcdef0123456789abcdef"


def test_an_old_key_reads_as_the_new_one() -> None:
    assert current_sensor_key("system_drive_free_gb") == "system_drive"
    assert current_sensor_key("memory_available_mb") == "memory_available"
    assert current_sensor_key("cpu_usage") == "cpu_usage"


def test_a_payload_from_an_older_client_is_read_under_the_new_keys() -> None:
    payload = {
        "cpu_usage": 3,
        "system_drive_free_gb": 120.5,
        "memory_available_mb": 8192,
        "attributes": {"system_drive_free_gb": {"drive": "C:", "total_gb": 476.0}, "cpu_usage": {}},
    }

    read = with_current_sensor_keys(payload)

    assert read["system_drive"] == 120.5
    assert read["memory_available"] == 8192
    assert "system_drive_free_gb" not in read
    assert read["attributes"]["system_drive"] == {"drive": "C:", "total_gb": 476.0}
    assert "system_drive_free_gb" not in read["attributes"]
    assert read["cpu_usage"] == 3
    # The payload given is left as it was.
    assert payload["system_drive_free_gb"] == 120.5


def test_a_client_sending_both_names_is_read_by_the_new_one() -> None:
    payload = {"system_drive": 120.5, "system_drive_free_gb": 120.5, "attributes": {"system_drive": {"drive": "C:"}, "system_drive_free_gb": {"drive": "C:"}}}

    read = with_current_sensor_keys(payload)

    assert read["system_drive"] == 120.5
    assert "system_drive_free_gb" not in read
    assert list(read["attributes"]) == ["system_drive"]


def test_a_payload_without_old_keys_is_the_same_object() -> None:
    payload = {"cpu_usage": 3, "attributes": {"cpu_usage": {}}}

    assert with_current_sensor_keys(payload) is payload


def test_the_advertised_list_folds_the_old_key_into_the_new() -> None:
    advertised = [
        {"key": "system_drive", "name": "System drive free space"},
        {"key": "system_drive_free_gb", "name": "System drive free space"},
        {"key": "memory_available_mb", "name": "Available memory"},
    ]

    assert _normalize_standard_sensors(advertised) == (
        ("memory_available", "Available memory"),
        ("system_drive", "System drive free space"),
    )


async def test_the_entity_made_under_the_old_key_keeps_its_entity_id(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, f"sensor_{SERIAL}_system_drive_free_gb", config_entry=entry, suggested_object_id="my_pc_system_drive_free_space"
    )

    async_migrate_renamed_sensor_entities(hass, entry)

    assert registry.async_get_entity_id("sensor", DOMAIN, f"sensor_{SERIAL}_system_drive") == old.entity_id
    assert registry.async_get_entity_id("sensor", DOMAIN, f"sensor_{SERIAL}_system_drive_free_gb") is None
    assert old.entity_id == "sensor.my_pc_system_drive_free_space"


async def test_a_leftover_old_entity_goes_when_the_new_one_already_exists(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", DOMAIN, f"sensor_{SERIAL}_memory_available_mb", config_entry=entry)
    new = registry.async_get_or_create("sensor", DOMAIN, f"sensor_{SERIAL}_memory_available", config_entry=entry)

    async_migrate_renamed_sensor_entities(hass, entry)

    assert registry.async_get_entity_id("sensor", DOMAIN, f"sensor_{SERIAL}_memory_available") == new.entity_id
    assert registry.async_get_entity_id("sensor", DOMAIN, f"sensor_{SERIAL}_memory_available_mb") is None


async def test_nothing_to_move_is_fine(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={})
    entry.add_to_hass(hass)

    async_migrate_renamed_sensor_entities(hass, entry)
