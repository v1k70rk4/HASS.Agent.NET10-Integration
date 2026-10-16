"""play_media hands the announce flag to the Windows client."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.hass_agent.const import CONF_HA_API, DOMAIN

SERIAL = "0123456789abcdef0123456789abcdef"
ENTITY_ID = "media_player.my_pc"
DEVICE = {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.9.3"}
SOUND = "http://ha.local:8123/api/tts_proxy/hello.mp3"


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


@pytest.fixture
async def pc(hass: HomeAssistant, mqtt_mock) -> MockConfigEntry:
    """An HA API PC whose tray app is up and reports an idle player."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        title="MY-PC",
        data={CONF_HA_API: True, "device": DEVICE, "apis": {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()

    hass.bus.async_fire("hass_agent_device_update", {
        "serial_number": SERIAL,
        "device": DEVICE,
        "apis": {"media_player": True},
    })
    await hass.async_block_till_done(wait_background_tasks=True)
    hass.data[DOMAIN][entry.entry_id]["app_online"] = True
    async_dispatcher_send(hass, f"hass_agent_media_state_{entry.entry_id}", {"state": "idle", "volume": 20})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID) is not None
    return entry


def _media_commands(events) -> list[dict]:
    return [event.data["payload"] for event in events if event.data.get("command_type") == "media_command"]


async def test_the_player_offers_announcements(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    features = hass.states.get(ENTITY_ID).attributes[ATTR_SUPPORTED_FEATURES]
    assert features & MediaPlayerEntityFeature.MEDIA_ANNOUNCE
    assert features & MediaPlayerEntityFeature.PLAY_MEDIA


async def test_an_announcement_carries_the_flag(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    events = async_capture_events(hass, "hass_agent_command")

    await hass.services.async_call(
        "media_player",
        "play_media",
        {ATTR_ENTITY_ID: ENTITY_ID, "media_content_type": "music", "media_content_id": SOUND, "announce": True},
        blocking=True,
    )

    assert _media_commands(events) == [{"command": "playmedia", "data": SOUND, "announce": True}]


async def test_ordinary_playback_looks_as_it_always_did(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    """No flag at all, so a client of any version reads the same message as before."""
    events = async_capture_events(hass, "hass_agent_command")

    await hass.services.async_call(
        "media_player",
        "play_media",
        {ATTR_ENTITY_ID: ENTITY_ID, "media_content_type": "music", "media_content_id": SOUND},
        blocking=True,
    )
    await hass.services.async_call(
        "media_player",
        "play_media",
        {ATTR_ENTITY_ID: ENTITY_ID, "media_content_type": "music", "media_content_id": SOUND, "announce": False},
        blocking=True,
    )

    assert _media_commands(events) == [
        {"command": "playmedia", "data": SOUND},
        {"command": "playmedia", "data": SOUND},
    ]
