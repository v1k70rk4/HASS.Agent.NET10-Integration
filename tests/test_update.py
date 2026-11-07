"""The update entity around an update: no stale "on" once the PC comes back."""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.hass_agent.const import DOMAIN

SERIAL = "0123456789abcdef0123456789abcdef"
DEVICE = {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.11.0"}
AVAILABILITY_TOPIC = f"hass.agent/devices/{SERIAL}/availability"
UPDATE_TOPIC = f"hass.agent/update/{SERIAL}/state"


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


@pytest.fixture
async def pc(hass: HomeAssistant, mqtt_mock) -> MockConfigEntry:
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


async def test_a_pending_update_shows_again_once_the_pc_says_so(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.12.0"))
    await _send(hass, AVAILABILITY_TOPIC, "offline")
    await _send(hass, AVAILABILITY_TOPIC, "online")

    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.12.0"))
    assert _state(hass) == "on"
