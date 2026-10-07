"""A PC on the HA API set up and reloaded the way Home Assistant does it."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.hass_agent.const import CONF_HA_API, DOMAIN

SERIAL = "0123456789abcdef0123456789abcdef"
ANNOUNCE = {"serial_number": SERIAL, "command_type": "announce"}


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


@pytest.fixture
async def ha_api_pc(hass: HomeAssistant, mqtt_mock) -> MockConfigEntry:
    """An HA API PC set up while Home Assistant runs, its first announce already sent."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        title="MY-PC",
        data={
            CONF_HA_API: True,
            "device": {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.9.0"},
            "apis": {},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    return entry


async def test_setup_asks_the_pc_to_announce(hass: HomeAssistant, mqtt_mock) -> None:
    events = async_capture_events(hass, "hass_agent_command")
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={CONF_HA_API: True, "device": {"name": "MY-PC"}, "apis": {}},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert [event.data for event in events] == []  # not while the setup runs

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    assert [event.data for event in events] == [ANNOUNCE]


async def test_reload_asks_again_after_its_setup(hass: HomeAssistant, ha_api_pc: MockConfigEntry) -> None:
    events = async_capture_events(hass, "hass_agent_command")

    assert await hass.config_entries.async_reload(ha_api_pc.entry_id)
    await hass.async_block_till_done()
    assert ha_api_pc.state is ConfigEntryState.LOADED
    assert [event.data for event in events] == []  # the answer loads platforms: not during the reload

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    assert [event.data for event in events] == [ANNOUNCE]


async def test_unloaded_pc_is_not_asked(hass: HomeAssistant, ha_api_pc: MockConfigEntry) -> None:
    events = async_capture_events(hass, "hass_agent_command")

    assert await hass.config_entries.async_reload(ha_api_pc.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(ha_api_pc.entry_id)
    await hass.async_block_till_done()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    assert events == []  # the pending request went with the entry
