"""The HA API commands for a PC with a Home Assistant user of its own (not an administrator)."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.hass_agent.const import CONF_HA_API, CONF_USER_ID, DOMAIN

SERIAL = "0123456789abcdef0123456789abcdef"
OTHER = "ffffffffffffffffffffffffffffffff"
DEVICE = {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.9.1"}
ANNOUNCE = {"serial_number": SERIAL, "device": DEVICE, "apis": {}}


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


@pytest.fixture
async def integration(hass: HomeAssistant, mqtt_mock) -> None:
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


async def _user_client(hass, hass_ws_client, name: str, admin: bool = False):
    """A WebSocket client for a user of the given kind, and that user."""
    user = await hass.auth.async_create_user(name, group_ids=["system-admin" if admin else "system-users"])
    refresh = await hass.auth.async_create_refresh_token(user, "https://example.com/")
    token = hass.auth.async_create_access_token(refresh)
    return await hass_ws_client(hass, access_token=token), user


def _entry(hass: HomeAssistant, user_id: str | None, serial: str = SERIAL) -> MockConfigEntry:
    data = {CONF_HA_API: True, "device": DEVICE, "apis": {}}
    if user_id is not None:
        data[CONF_USER_ID] = user_id
    entry = MockConfigEntry(domain=DOMAIN, unique_id=serial, title="MY-PC", data=data)
    entry.add_to_hass(hass)
    return entry


async def _fire(client, event_type: str, data: dict) -> dict:
    await client.send_json_auto_id({"type": "hass_agent/fire", "event_type": event_type, "event_data": data})
    return await client.receive_json()


async def test_new_pc_of_a_plain_user_waits_for_an_administrator(hass, integration, hass_ws_client) -> None:
    client, user = await _user_client(hass, hass_ws_client, "pc-user")
    events = async_capture_events(hass, "hass_agent_device_update")

    result = await _fire(client, "hass_agent_device_update", ANNOUNCE)
    await hass.async_block_till_done()

    assert result["success"] is False
    assert result["error"]["code"] == "unauthorized"
    assert events == []  # nothing reaches the listeners before the approval
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["step_id"] for flow in flows] == ["confirm"]

    # The administrator confirms it under Discovered: the PC is bound to its user.
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data[CONF_USER_ID] == user.id

    sensors = async_capture_events(hass, "hass_agent_sensor_update")
    result = await _fire(client, "hass_agent_sensor_update", {"serial_number": SERIAL, "sensors": []})
    await hass.async_block_till_done()
    assert result["success"] is True
    assert len(sensors) == 1


async def test_a_pc_cannot_speak_for_another_pc(hass, integration, hass_ws_client) -> None:
    client, user = await _user_client(hass, hass_ws_client, "pc-user")
    _entry(hass, user.id)
    _entry(hass, "someone-else", serial=OTHER)

    result = await _fire(client, "hass_agent_sensor_update", {"serial_number": OTHER, "sensors": []})

    assert result["error"]["code"] == "unauthorized"


async def test_another_user_for_a_pc_needs_approval(hass, integration, hass_ws_client) -> None:
    client, user = await _user_client(hass, hass_ws_client, "new-user")
    entry = _entry(hass, "the-old-user")

    result = await _fire(client, "hass_agent_device_update", ANNOUNCE)
    await hass.async_block_till_done()

    assert result["error"]["code"] == "unauthorized"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["step_id"] for flow in flows] == ["approve_user"]
    assert entry.data[CONF_USER_ID] == "the-old-user"  # nothing changes before the approval

    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {})
    assert result["reason"] == "user_approved"
    assert entry.data[CONF_USER_ID] == user.id


async def test_ignoring_the_approval_keeps_the_pc(hass, integration, hass_ws_client) -> None:
    client, _ = await _user_client(hass, hass_ws_client, "new-user")
    entry = _entry(hass, "the-old-user")
    await _fire(client, "hass_agent_device_update", ANNOUNCE)
    await hass.async_block_till_done()

    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "ignore"}, data={"unique_id": SERIAL, "title": "MY-PC"}
    )

    assert hass.config_entries.async_get_entry(entry.entry_id) is entry
    assert entry.data[CONF_USER_ID] == "the-old-user"
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_an_administrator_is_let_through(hass, integration, hass_ws_client) -> None:
    client, _ = await _user_client(hass, hass_ws_client, "admin", admin=True)
    _entry(hass, None)
    events = async_capture_events(hass, "hass_agent_sensor_update")

    result = await _fire(client, "hass_agent_sensor_update", {"serial_number": SERIAL, "sensors": []})
    await hass.async_block_till_done()

    assert result["success"] is True
    assert len(events) == 1


@pytest.mark.parametrize(
    ("event_type", "data", "code"),
    [
        ("call_service", {"serial_number": SERIAL}, "invalid_format"),             # not one of ours
        ("hass_agent_sensor_update", {"serial_number": "+"}, "invalid_format"),     # no usable serial
        ("hass_agent_command", {"serial_number": SERIAL, "command_type": "button_command"}, "unauthorized"),
    ],
)
async def test_only_the_clients_own_events(hass, integration, hass_ws_client, event_type, data, code) -> None:
    client, user = await _user_client(hass, hass_ws_client, "pc-user")
    _entry(hass, user.id)

    result = await _fire(client, event_type, data)

    assert result["success"] is False
    assert result["error"]["code"] == code


async def test_the_tray_app_may_ask_its_service_to_install(hass, integration, hass_ws_client) -> None:
    client, user = await _user_client(hass, hass_ws_client, "pc-user")
    _entry(hass, user.id)

    result = await _fire(
        client, "hass_agent_command", {"serial_number": SERIAL, "command_type": "install_update", "target": "service"}
    )

    assert result["success"] is True


async def test_subscription_passes_on_only_this_pcs_commands(hass, integration, hass_ws_client) -> None:
    client, user = await _user_client(hass, hass_ws_client, "pc-user")
    _entry(hass, user.id)
    await client.send_json_auto_id({"type": "hass_agent/subscribe", "serial_number": SERIAL})
    assert (await client.receive_json())["success"] is True

    hass.bus.async_fire("hass_agent_command", {"serial_number": OTHER, "command_type": "announce"})
    hass.bus.async_fire("hass_agent_command", {"serial_number": SERIAL, "command_type": "announce"})
    await hass.async_block_till_done()

    message = await client.receive_json()
    assert message["type"] == "event"
    assert message["event"]["event_type"] == "hass_agent_command"
    assert message["event"]["data"] == {"serial_number": SERIAL, "command_type": "announce"}


async def test_no_commands_before_the_approval(hass, integration, hass_ws_client) -> None:
    client, user = await _user_client(hass, hass_ws_client, "pc-user")
    entry = _entry(hass, "the-old-user")
    await client.send_json_auto_id({"type": "hass_agent/subscribe", "serial_number": SERIAL})
    assert (await client.receive_json())["success"] is True

    hass.bus.async_fire("hass_agent_command", {"serial_number": SERIAL, "command_type": "announce"})
    await hass.async_block_till_done()
    # Approved now: the same subscription carries the next command.
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_USER_ID: user.id})
    hass.bus.async_fire("hass_agent_command", {"serial_number": SERIAL, "command_type": "update_install"})
    await hass.async_block_till_done()

    message = await client.receive_json()
    assert message["event"]["data"]["command_type"] == "update_install"

