"""The announce request that HA API clients answer with their device data."""

from __future__ import annotations

from homeassistant.core import CoreState, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.hass_agent import _async_request_announce
from custom_components.hass_agent.const import DOMAIN

SERIAL = "0123456789abcdef0123456789abcdef"


async def test_announce_is_asked_once_home_assistant_has_started(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL)
    entry.add_to_hass(hass)
    events = async_capture_events(hass, "hass_agent_command")
    hass.set_state(CoreState.not_running)

    _async_request_announce(hass, entry)
    await hass.async_block_till_done()
    assert events == []  # not while Home Assistant is still starting

    await hass.async_start()
    await hass.async_block_till_done()

    assert [event.data for event in events] == [{"serial_number": SERIAL, "command_type": "announce"}]
