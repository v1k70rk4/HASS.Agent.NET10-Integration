"""A PC's sensor or button list changing while another integration has a long task running.

Rebuilding a platform waited for every task of Home Assistant (``hass.async_block_till_done``),
so one long-running task elsewhere kept the sensors unloaded, and unavailable, for as long
as it ran.
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hass_agent import handle_apis_changed
from custom_components.hass_agent.const import CONF_HA_API, DOMAIN

SERIAL = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


def _apis(*keys: str, commands: tuple[str, ...] = ()) -> dict:
    return {
        "system_sensors": True,
        "standard_sensors": [{"key": key, "name": key.replace("_", " ").capitalize()} for key in keys],
        "buttons": bool(commands),
        "commands": [{"name": name, "display_name": name.capitalize()} for name in commands],
    }


@pytest.fixture
async def pc(hass: HomeAssistant, mqtt_mock) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        title="MY-PC",
        data={CONF_HA_API: True, "device": {"name": "MY-PC"}, "apis": {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _sensor_ids(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    return {
        item.unique_id
        for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if item.domain == "sensor"
    }


async def test_a_changed_sensor_list_is_applied_while_another_task_runs(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    await handle_apis_changed(hass, pc, _apis("cpu_usage"))
    await hass.async_block_till_done()
    assert f"sensor_{SERIAL}_cpu_usage" in _sensor_ids(hass, pc)

    # Another integration's task that does not end soon.
    forever = asyncio.Event()
    blocker = hass.async_create_task(forever.wait(), "someone else's long task")
    try:
        await asyncio.wait_for(handle_apis_changed(hass, pc, _apis("cpu_usage", "sleep_blocked")), timeout=5)
    finally:
        forever.set()
        await blocker

    await hass.async_block_till_done()
    data = hass.data[DOMAIN][pc.entry_id]
    assert data["loaded"]["sensor"] is True
    assert {f"sensor_{SERIAL}_cpu_usage", f"sensor_{SERIAL}_sleep_blocked"} <= _sensor_ids(hass, pc)
    assert hass.states.get("sensor.my_pc_cpu_usage") is not None
    assert hass.states.get("sensor.my_pc_cpu_usage").state != "unavailable"


async def test_a_changed_button_list_is_applied_while_another_task_runs(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    await handle_apis_changed(hass, pc, _apis(commands=("shutdown",)))
    await hass.async_block_till_done()

    forever = asyncio.Event()
    blocker = hass.async_create_task(forever.wait(), "someone else's long task")
    try:
        await asyncio.wait_for(handle_apis_changed(hass, pc, _apis(commands=("shutdown", "restart"))), timeout=5)
    finally:
        forever.set()
        await blocker

    await hass.async_block_till_done()
    assert hass.data[DOMAIN][pc.entry_id]["loaded"]["button"] is True
