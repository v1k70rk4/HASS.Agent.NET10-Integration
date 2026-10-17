"""The tray app's availability when it moves between MQTT and the HA API."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.hass_agent import WS_AVAILABILITY_TIMEOUT
from custom_components.hass_agent.const import DOMAIN

SERIAL = "0123456789abcdef0123456789abcdef"
DEVICE = {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.9.3"}
AVAILABILITY_TOPIC = f"hass.agent/devices/{SERIAL}/availability"


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


@pytest.fixture
async def pc(hass: HomeAssistant, mqtt_mock) -> MockConfigEntry:
    """An MQTT PC, which the integration also listens to on the HA API (the failover)."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        title="MY-PC",
        data={"device": DEVICE, "apis": {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _app_online(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
    return bool(hass.data[DOMAIN][entry.entry_id].get("app_online", True))


async def _heartbeat(hass: HomeAssistant) -> None:
    hass.bus.async_fire("hass_agent_availability", {"serial_number": SERIAL, "online": True})
    await hass.async_block_till_done()


async def _mqtt_availability(hass: HomeAssistant, payload: str) -> None:
    async_fire_mqtt_message(hass, AVAILABILITY_TOPIC, payload)
    await hass.async_block_till_done()


async def _heartbeat_timeout_passes(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=WS_AVAILABILITY_TIMEOUT + 5))
    await hass.async_block_till_done()


async def test_app_moving_from_the_ha_api_to_mqtt_stays_online(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    """The last heartbeat's timer must not take down an app that said online on MQTT since."""
    await _heartbeat(hass)
    assert _app_online(hass, pc)

    # MQTT switched on in the app: it leaves the HA API without a goodbye and announces
    # itself on the broker.
    await _mqtt_availability(hass, "online")
    assert _app_online(hass, pc)

    await _heartbeat_timeout_passes(hass)
    assert _app_online(hass, pc)


async def test_app_moving_from_mqtt_to_the_ha_api_still_times_out(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    """A retained online on the broker is stale once the app heartbeats on the HA API."""
    await _mqtt_availability(hass, "online")
    await _heartbeat(hass)
    assert _app_online(hass, pc)

    # The app dies on the HA API, which has no Last Will: the heartbeats stop.
    await _heartbeat_timeout_passes(hass)
    assert not _app_online(hass, pc)


async def test_failover_and_back(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    """Broker gone: Last Will, heartbeats on the HA API. Broker back: online on MQTT, heartbeats stop."""
    await _mqtt_availability(hass, "online")
    await _mqtt_availability(hass, "offline")
    assert not _app_online(hass, pc)

    await _heartbeat(hass)
    assert _app_online(hass, pc)

    await _mqtt_availability(hass, "online")
    await _heartbeat_timeout_passes(hass)
    assert _app_online(hass, pc)


async def test_heartbeats_alone_still_time_out(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    """Nothing changes for a PC that only ever used the HA API."""
    await _heartbeat(hass)
    await _heartbeat_timeout_passes(hass)
    assert not _app_online(hass, pc)
