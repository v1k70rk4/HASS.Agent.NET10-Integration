"""The update entity around an update: no stale "on" once the PC comes back."""

from __future__ import annotations

import json
from typing import Any

import pytest
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    CONF_HA_API,
    DOMAIN,
    EVENT_UPDATE_AVAILABLE,
    UPDATE_ANNOUNCED_DATA,
    UPDATE_ANNOUNCED_STORE,
)
from custom_components.hass_agent.device_trigger import async_get_triggers

SERIAL = "0123456789abcdef0123456789abcdef"
DEVICE = {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.11.0"}
AVAILABILITY_TOPIC = f"hass.agent/devices/{SERIAL}/availability"
UPDATE_TOPIC = f"hass.agent/update/{SERIAL}/state"
INSTALL_TOPIC = f"hass.agent/update/{SERIAL}/install"


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


def _update_state(installed: str, latest: str, remote_install: bool | None = None) -> str:
    state: dict[str, Any] = {
        "installed_version": installed,
        "latest_version": latest,
        "update_available": installed != latest,
        "release_url": f"https://github.com/v1k70rk4/HASS.Agent.NET10/releases/tag/v{latest}",
    }
    # An agent before 10.13.1 sends nothing about it.
    if remote_install is not None:
        state["remote_install"] = remote_install
    return json.dumps(state)


def _entity_id(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("update", DOMAIN, f"update_{SERIAL}_app")
    assert entity_id is not None
    return entity_id


def _may_install(hass: HomeAssistant) -> bool:
    features = hass.states.get(_entity_id(hass)).attributes[ATTR_SUPPORTED_FEATURES]
    return bool(features & UpdateEntityFeature.INSTALL)


def _install_requests(mqtt_mock: MqttMockHAClient) -> list[Any]:
    return [call for call in mqtt_mock.async_publish.call_args_list if call.args[0] == INSTALL_TOPIC]


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


async def test_the_tag_of_a_release_is_a_version(hass: HomeAssistant, pc: MockConfigEntry) -> None:
    # What the client sends for the version it offers: the release's tag as GitHub has it.
    events = async_capture_events(hass, EVENT_UPDATE_AVAILABLE)

    await _send(hass, UPDATE_TOPIC, _update_state("10.13.0", "v10.14.0-beta.1"))

    assert [event.data["latest_version"] for event in events] == ["v10.14.0-beta.1"]
    assert [event.data["installed_version"] for event in events] == ["10.13.0"]
    assert hass.data[UPDATE_ANNOUNCED_DATA]["versions"] == {SERIAL: "v10.14.0-beta.1"}


@pytest.mark.parametrize(
    "latest",
    [
        "the newest one",
        "10.14.0 and more after it",
        "10.14.0" + chr(10) + "a line below it",
        "10.14.0-" + "x" * 10_000,
        "1" * 10_000,
        "10.14.0.1.2",
    ],
)
async def test_what_is_not_a_version_is_neither_announced_nor_kept(
    hass: HomeAssistant, pc: MockConfigEntry, latest: str
) -> None:
    # The state is the PC's to send, and on MQTT anyone's who may publish on its topic:
    # a text of any length would go into the event and into the file kept across restarts.
    events = async_capture_events(hass, EVENT_UPDATE_AVAILABLE)

    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", latest))

    assert events == []
    assert hass.data[UPDATE_ANNOUNCED_DATA]["versions"] == {}


async def test_an_installed_version_that_is_not_one_is_left_out_of_the_event(
    hass: HomeAssistant, pc: MockConfigEntry
) -> None:
    events = async_capture_events(hass, EVENT_UPDATE_AVAILABLE)

    await _send(hass, UPDATE_TOPIC, _update_state("x" * 10_000, "10.13.0"))

    assert [event.data["latest_version"] for event in events] == ["10.13.0"]
    assert [event.data["installed_version"] for event in events] == [None]


async def test_a_kept_text_that_is_not_a_version_is_not_kept_on(
    hass: HomeAssistant, mqtt_mock: MqttMockHAClient, hass_storage: dict[str, Any]
) -> None:
    # What a run before this fix could be made to keep: dropped when it is read, so the
    # version the PC really offers is announced.
    hass_storage[UPDATE_ANNOUNCED_STORE] = {"version": 1, "minor_version": 1, "key": UPDATE_ANNOUNCED_STORE, "data": {SERIAL: "x" * 10_000}}
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={"device": DEVICE, "apis": {}})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, SERIAL)}, name="MY-PC")
    assert hass.data[UPDATE_ANNOUNCED_DATA]["versions"] == {}
    events = async_capture_events(hass, EVENT_UPDATE_AVAILABLE)

    await _send(hass, UPDATE_TOPIC, _update_state("10.11.0", "10.12.0"))

    assert [event.data["latest_version"] for event in events] == ["10.12.0"]


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


async def test_the_install_goes_to_the_pc(
    hass: HomeAssistant, pc: MockConfigEntry, mqtt_mock: MqttMockHAClient
) -> None:
    # An agent that says nothing about it (before 10.13.1), and one that says it takes it.
    commands = async_capture_events(hass, "hass_agent_command")

    for remote_install in (None, True):
        await _send(hass, UPDATE_TOPIC, _update_state("10.13.0", "10.13.1", remote_install))
        assert _may_install(hass)
        await hass.services.async_call("update", "install", {ATTR_ENTITY_ID: _entity_id(hass)}, blocking=True)

    assert len(_install_requests(mqtt_mock)) == 2
    assert [event.data["command_type"] for event in commands] == ["update_install", "update_install"]


async def test_a_pc_that_installs_updates_only_at_the_pc_offers_no_install(
    hass: HomeAssistant, pc: MockConfigEntry, mqtt_mock: MqttMockHAClient
) -> None:
    commands = async_capture_events(hass, "hass_agent_command")

    await _send(hass, UPDATE_TOPIC, _update_state("10.13.1", "10.14.0", remote_install=False))

    # The new version shows; the Install button does not.
    assert _state(hass) == "on"
    assert hass.states.get(_entity_id(hass)).attributes["latest_version"] == "10.14.0"
    assert not _may_install(hass)

    # Asked for all the same (an automation, a script): refused here, nothing goes to the PC.
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("update", "install", {ATTR_ENTITY_ID: _entity_id(hass)}, blocking=True)
    assert _install_requests(mqtt_mock) == []
    assert commands == []


async def test_the_install_is_back_once_the_pc_takes_it_again(
    hass: HomeAssistant, pc: MockConfigEntry, mqtt_mock: MqttMockHAClient
) -> None:
    await _send(hass, UPDATE_TOPIC, _update_state("10.13.1", "10.14.0", remote_install=False))
    assert not _may_install(hass)

    # The switch on the PC was turned off again: it sends its state at once.
    await _send(hass, UPDATE_TOPIC, _update_state("10.13.1", "10.14.0", remote_install=True))
    assert _may_install(hass)

    await hass.services.async_call("update", "install", {ATTR_ENTITY_ID: _entity_id(hass)}, blocking=True)
    assert len(_install_requests(mqtt_mock)) == 1


async def test_the_entity_itself_refuses_when_the_pc_does_not_take_the_install(
    hass: HomeAssistant, pc: MockConfigEntry, mqtt_mock: MqttMockHAClient
) -> None:
    # Past Home Assistant's own check of the feature: the entity's install says no by itself.
    await _send(hass, UPDATE_TOPIC, _update_state("10.13.1", "10.14.0", remote_install=False))
    entity = hass.data["update"].get_entity(_entity_id(hass))

    with pytest.raises(HomeAssistantError, match="only at the PC"):
        await entity.async_install(None, False)
    assert _install_requests(mqtt_mock) == []


@pytest.fixture
async def ha_api_pc(hass: HomeAssistant, mqtt_mock: MqttMockHAClient) -> MockConfigEntry:
    """A PC on the HA API: its state comes as events, and so do the commands to it."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={CONF_HA_API: True, "device": DEVICE, "apis": {}}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, SERIAL)}, name="MY-PC"
    )
    return entry


async def _send_event(hass: HomeAssistant, state: str) -> None:
    hass.bus.async_fire("hass_agent_update_state", {"serial_number": SERIAL, "state": json.loads(state)})
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_on_the_ha_api_the_install_goes_out_as_an_event_only(
    hass: HomeAssistant, ha_api_pc: MockConfigEntry, mqtt_mock: MqttMockHAClient
) -> None:
    commands = async_capture_events(hass, "hass_agent_command")

    await _send_event(hass, _update_state("10.13.0", "10.13.1", remote_install=True))
    assert _may_install(hass)
    await hass.services.async_call("update", "install", {ATTR_ENTITY_ID: _entity_id(hass)}, blocking=True)

    assert [(event.data["serial_number"], event.data["command_type"]) for event in commands] == [(SERIAL, "update_install")]
    assert _install_requests(mqtt_mock) == []


async def test_on_the_ha_api_a_pc_that_installs_only_at_the_pc_offers_no_install(
    hass: HomeAssistant, ha_api_pc: MockConfigEntry, mqtt_mock: MqttMockHAClient
) -> None:
    commands = async_capture_events(hass, "hass_agent_command")

    await _send_event(hass, _update_state("10.13.1", "10.14.0", remote_install=False))

    assert _state(hass) == "on"
    assert not _may_install(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("update", "install", {ATTR_ENTITY_ID: _entity_id(hass)}, blocking=True)
    assert commands == []

    # Turned off again on the PC: the next state brings Install back.
    await _send_event(hass, _update_state("10.13.1", "10.14.0", remote_install=True))
    assert _may_install(hass)


async def test_a_state_meant_for_another_pc_changes_nothing_here(
    hass: HomeAssistant, ha_api_pc: MockConfigEntry
) -> None:
    await _send_event(hass, _update_state("10.13.1", "10.14.0", remote_install=True))
    assert _may_install(hass)

    # Another PC on the same Home Assistant set its own switch.
    hass.bus.async_fire(
        "hass_agent_update_state",
        {"serial_number": "f" * 32, "state": json.loads(_update_state("10.13.1", "10.14.0", remote_install=False))},
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert _may_install(hass)

