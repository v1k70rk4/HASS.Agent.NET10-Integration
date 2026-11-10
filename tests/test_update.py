"""The update entity around an update: no stale "on" once the PC comes back."""

from __future__ import annotations

import json
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_mqtt_message,
)
from pytest_homeassistant.typing import MqttMockHAClient

from custom_components.hass_agent.const import (
    DOMAIN,
    EVENT_UPDATE_AVAILABLE,
    UPDATE_ANNOUNCED_STORE,
)
from custom_components.hass_agent.device_trigger import async_get_triggers

SERIAL = "0123456789abcdef0123456789abcdef"
DEVICE = {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.11.0"}
AVAILABILITY_TOPIC = f"hass.agent/devices/{SERIAL}/availability"
UPDATE_TOPIC = f"hass.agent/update/{SERIAL}/state"


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


@pytest.fixture
async def pc(hass: HomeAssistant, mqtt_mock: MqttMockHAClient) -> MockConfigEntry:
    """An MQTT PC with the tray app online and no service."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={"device": DEVICE, "apis": {}})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # The device the PC's discovery message makes; the update entity hangs on it.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, SERIAL)}, name="MY-PC"
    )
    return entry


async def _send(hass: HomeAssistant, topic: str, payload: str) -> None:
    async_fire_mqtt_message(hass, topic, payload)
    # The first state sets the update platform up in a background task.
    await hass.async_block_till_done(wait_background_tasks=True)


def _update_state(installed: str, latest: str) -> str:
    return json.dumps({
        "installed_version": installed,
        "latest_version": latest,
        "update_available": installed != latest,
        "release_url": f"https://github.com/v1k70rk4/HASS.Agent.NET10/releases/tag/v{latest}",
    })


def _state(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("update", DOMAIN, f"update_{SERIAL}_app")
    assert entity_id is not None
    return hass.states.get(entity_id).state


async def test_an_installed_update_does_not_come_back_as_available(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.12.0"))
    assert _state(hass) == "on"

    # Setup stops the app; the new version comes online before it sends its state.
    await _send(hass, AVAILABILITY_TOPIC, "offline")
    assert _state(hass) == "unavailable"
    await _send(hass, AVAILABILITY_TOPIC, "online")
    assert _state(hass) == "unknown"

    await _send(hass, UPDATE_TOPIC, _update_state("10.12.0", "10.12.0"))
    assert _state(hass) == "off"


async def test_each_version_is_announced_once(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    events = async_capture_events(hass, EVENT_UPDATE_AVAILABLE)

    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.12.0"))
    assert len(events) == 1
    assert events[0].data["serial_number"] == SERIAL
    assert events[0].data["device_name"] == "MY-PC"
    assert events[0].data["installed_version"] == "10.11.0"
    assert events[0].data["latest_version"] == "10.12.0"
    assert events[0].data["release_url"].startswith("https://github.com/")

    # The same update after the PC was off: unknown, then on again, and no second event.
    await _send(hass, AVAILABILITY_TOPIC, "offline")
    await _send(hass, AVAILABILITY_TOPIC, "online")
    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.12.0"))
    assert _state(hass) == "on"
    assert len(events) == 1

    # Installed: nothing to announce. A newer one later: announced.
    await _send(hass, UPDATE_TOPIC, _update_state("10.12.0", "10.12.0"))
    await _send(hass, UPDATE_TOPIC, _update_state("10.12.0", "10.13.0"))
    assert [event.data["latest_version"] for event in events] == ["10.12.0", "10.13.0"]


async def test_a_pc_whose_update_entity_comes_from_mqtt_discovery_is_announced_too(
    hass: HomeAssistant, pc: MockConfigEntry
) -> None:
    # An agent before 10.7.3 has its update entity made by MQTT discovery, and the
    # integration adds no second one. The event does not depend on whose entity it is.
    er.async_get(hass).async_get_or_create("update", "mqtt", f"{SERIAL}_hass_agent_net10_update")
    events = async_capture_events(hass, EVENT_UPDATE_AVAILABLE)

    await _send(hass, UPDATE_TOPIC, _update_state("10.7.0", "10.13.0"))

    assert [event.data["latest_version"] for event in events] == ["10.13.0"]
    assert er.async_get(hass).async_get_entity_id("update", DOMAIN, f"update_{SERIAL}_app") is None


async def test_the_announced_version_outlives_a_restart_of_home_assistant(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient, hass_storage: dict[str, Any]
) -> None:
    # What a run before this one announced, as Home Assistant keeps it.
    hass_storage[UPDATE_ANNOUNCED_STORE] = {"version": 1, "minor_version": 1, "key": UPDATE_ANNOUNCED_STORE, "data": {SERIAL: "10.12.0"}}
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={"device": DEVICE, "apis": {}})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, SERIAL)}, name="MY-PC")
    events = async_capture_events(hass, EVENT_UPDATE_AVAILABLE)

    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.12.0"))
    assert events == []

    # A version that came out meanwhile, while the PC was off: announced on its first state.
    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.13.0"))
    assert len(events) == 1


async def test_every_pc_offers_the_update_trigger(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=pc.entry_id, identifiers={(DOMAIN, SERIAL)}, name="MY-PC"
    )
    types = {trigger["type"] for trigger in await async_get_triggers(hass, device.id)}
    assert "update_available" in types


async def test_a_pending_update_shows_again_once_the_pc_says_so(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.12.0"))
    await _send(hass, AVAILABILITY_TOPIC, "offline")
    await _send(hass, AVAILABILITY_TOPIC, "online")

    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.12.0"))
    assert _state(hass) == "on"
