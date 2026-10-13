"""The media player's power options: off instead of unavailable, turn on and turn off."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_get_device_automations,
)

from custom_components.hass_agent.const import (
    CONF_HA_API,
    CONF_MEDIA_PLAYER_POWER,
    CONF_MEDIA_PLAYER_SERVICE_STATE,
    CONF_MEDIA_PLAYER_TURN_OFF,
    CONF_MEDIA_PLAYER_TURN_OFF_SCRIPT,
    CONF_MEDIA_PLAYER_TURN_ON_SCRIPT,
    DOMAIN,
    EVENT_TURN_OFF_REQUESTED,
    EVENT_TURN_ON_REQUESTED,
)

SERIAL = "0123456789abcdef0123456789abcdef"
ENTITY_ID = "media_player.my_pc"
DEVICE = {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.9.2"}


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


@pytest.fixture
async def pc(hass: HomeAssistant, mqtt_mock) -> MockConfigEntry:
    """An HA API PC set up while Home Assistant runs."""
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

    # The tray app answers the announce: with a media player, the platform is set up.
    _announce(hass, ["sleep"])
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(ENTITY_ID) is not None
    return entry


def _announce(hass: HomeAssistant, commands: list[str]) -> None:
    hass.bus.async_fire("hass_agent_device_update", {
        "serial_number": SERIAL,
        "device": DEVICE,
        "apis": {
            "media_player": True,
            "buttons": True,
            "commands": [{"name": name} for name in commands],
        },
    })


async def _set_options(hass: HomeAssistant, entry: MockConfigEntry, **options) -> None:
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()


async def _report(hass: HomeAssistant, entry: MockConfigEntry, commands: list[str]) -> None:
    """The tray app is up, offers these commands and reports an idle player."""
    _announce(hass, commands)
    await hass.async_block_till_done(wait_background_tasks=True)
    hass.data[DOMAIN][entry.entry_id]["app_online"] = True
    async_dispatcher_send(hass, f"hass_agent_media_state_{entry.entry_id}", {"state": "idle", "volume": 20})
    await hass.async_block_till_done()


async def test_without_the_option_nothing_changes(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    state = hass.states.get(ENTITY_ID)
    assert state.state == STATE_UNAVAILABLE

    await _report(hass, pc, ["sleep"])
    features = hass.states.get(ENTITY_ID).attributes[ATTR_SUPPORTED_FEATURES]
    assert not features & MediaPlayerEntityFeature.TURN_ON
    assert not features & MediaPlayerEntityFeature.TURN_OFF


async def test_a_silent_pc_is_off_and_can_be_turned_on(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    await _set_options(hass, pc, **{CONF_MEDIA_PLAYER_POWER: True})

    state = hass.states.get(ENTITY_ID)
    assert state.state == MediaPlayerState.OFF
    assert state.attributes[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.TURN_ON
    assert state.attributes[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.TURN_OFF

    events = async_capture_events(hass, EVENT_TURN_ON_REQUESTED)
    await hass.services.async_call("media_player", "turn_on", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True)
    assert [event.data["serial_number"] for event in events] == [SERIAL]


async def test_closed_app_on_a_running_pc_is_unavailable(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    await _set_options(hass, pc, **{CONF_MEDIA_PLAYER_POWER: True})
    hass.bus.async_fire("hass_agent_service_update", {"serial_number": SERIAL, "status": {"online": True}})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    # Switched off in the options: off whatever the service says.
    await _set_options(hass, pc, **{CONF_MEDIA_PLAYER_SERVICE_STATE: False})
    assert hass.states.get(ENTITY_ID).state == MediaPlayerState.OFF


async def test_turn_on_and_off_run_their_scripts(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    assert await async_setup_component(hass, "script", {
        "script": {
            "wake_pc": {"sequence": [{"event": "wake_pc_ran", "event_data": {"serial": "{{ serial_number }}"}}]},
            "pc_off": {"sequence": [{"event": "pc_off_ran"}]},
        }
    })
    await _set_options(hass, pc, **{
        CONF_MEDIA_PLAYER_POWER: True,
        CONF_MEDIA_PLAYER_TURN_ON_SCRIPT: "script.wake_pc",
        CONF_MEDIA_PLAYER_TURN_OFF_SCRIPT: "script.pc_off",
    })
    woken = async_capture_events(hass, "wake_pc_ran")
    off = async_capture_events(hass, "pc_off_ran")
    off_requested = async_capture_events(hass, EVENT_TURN_OFF_REQUESTED)

    await hass.services.async_call("media_player", "turn_on", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True)
    await hass.async_block_till_done()
    assert [event.data["serial"] for event in woken] == [SERIAL]

    await _report(hass, pc, ["sleep"])
    await hass.services.async_call("media_player", "turn_off", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True)
    await hass.async_block_till_done()
    assert len(off) == 1
    assert len(off_requested) == 1  # no command chosen: the trigger and the script only


async def test_turn_off_runs_the_chosen_command(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    await _set_options(hass, pc, **{CONF_MEDIA_PLAYER_POWER: True, CONF_MEDIA_PLAYER_TURN_OFF: "sleep"})
    await _report(hass, pc, ["sleep"])
    assert hass.states.get(ENTITY_ID).state == MediaPlayerState.IDLE

    commands = async_capture_events(hass, "hass_agent_command")
    await hass.services.async_call("media_player", "turn_off", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True)
    sent = [event.data for event in commands if event.data.get("command_type") == "button_command"]
    assert sent == [{
        "serial_number": SERIAL,
        "command_type": "button_command",
        "target": "app",
        "payload": {"command": "sleep"},
    }]


async def test_turn_off_says_when_the_pc_does_not_offer_the_command(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    await _set_options(hass, pc, **{CONF_MEDIA_PLAYER_POWER: True, CONF_MEDIA_PLAYER_TURN_OFF: "hibernate"})
    await _report(hass, pc, ["sleep"])

    with pytest.raises(HomeAssistantError, match="hibernate"):
        await hass.services.async_call("media_player", "turn_off", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True)


async def test_the_turn_on_trigger_comes_with_the_option(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    device_id = er.async_get(hass).async_get(ENTITY_ID).device_id
    device = dr.async_get(hass).async_get(device_id)
    assert device is not None

    def types(triggers) -> set[str]:
        return {trigger["type"] for trigger in triggers}

    triggers = types(await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id))
    assert not {"turn_on", "turn_off"} & triggers

    await _set_options(hass, pc, **{CONF_MEDIA_PLAYER_POWER: True})
    triggers = types(await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id))
    assert {"turn_on", "turn_off"} <= triggers

    assert await async_setup_component(hass, "automation", {
        "automation": {
            "trigger": {"platform": "device", "domain": DOMAIN, "device_id": device.id, "type": "turn_on"},
            "action": {"event": "woken"},
        }
    })
    woken = async_capture_events(hass, "woken")
    await hass.services.async_call("media_player", "turn_on", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True)
    await hass.async_block_till_done()
    assert len(woken) == 1
