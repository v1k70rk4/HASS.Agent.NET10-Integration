"""What a PC, or anything that can publish to the broker, must not be able to do."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hass_agent.config_flow import valid_serial
from custom_components.hass_agent.const import CONF_HA_API, DOMAIN
from custom_components.hass_agent.event import own_device
from custom_components.hass_agent.notify import _prepare_image
from custom_components.hass_agent.update import HassAgentUpdate

SERIAL = "0123456789abcdef0123456789abcdef"
DEVICE = {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.9.1"}


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


# --- pictures: only paths that hold pictures are signed -------------------------------------

@pytest.mark.parametrize(
    "image",
    [
        "/api/states",
        "/api/history/period?filter_entity_id=lock.front",
        "/local/../api/states",
        "/local/./x.jpg",
        "/local//x.jpg",
        "/auth/token",
        "/local\\..\\api\\states",
    ],
)
async def test_other_paths_are_not_signed(hass: HomeAssistant, image: str) -> None:
    with patch("custom_components.hass_agent.notify.async_sign_path") as sign:
        prepared = _prepare_image(hass, {"image": image, "style": "toast"})

    sign.assert_not_called()
    assert prepared == {"style": "toast"}


@pytest.mark.parametrize(
    "image",
    ["/local/doorbell.jpg", "/media/local/cam.png", "/api/camera_proxy/camera.front?width=640", "image.snapshot"],
)
async def test_picture_paths_are_signed(hass: HomeAssistant, image: str) -> None:
    with patch("custom_components.hass_agent.notify.async_sign_path", return_value="/signed") as sign:
        prepared = _prepare_image(hass, {"image": image})

    sign.assert_called_once()
    assert prepared["image_path"] == "/signed"


# --- serial numbers ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("serial", "valid"),
    [
        (SERIAL, True),
        ("6f9619ff-8b86-d011-b42d-00c04fc964ff", True),   # the classic client's form
        ("+", False),
        ("#", False),
        ("a/b", False),
        (f"{SERIAL}_cpu", False),
        ("", False),
        ("x" * 65, False),
        (42, False),
    ],
)
def test_serial_numbers(serial, valid: bool) -> None:
    assert valid_serial(serial) is valid


# --- discovery over MQTT -------------------------------------------------------------------------

def _discovery(topic_serial: str, serial: str = SERIAL, name: str = "MY-PC") -> MqttServiceInfo:
    return MqttServiceInfo(
        topic=f"hass.agent/devices/{topic_serial}",
        payload=json.dumps({"serial_number": serial, "device": {**DEVICE, "name": name}, "apis": {}}),
        qos=0,
        retain=True,
        subscribed_topic="hass.agent/devices/#",
        timestamp=0,
    )


async def test_payload_for_another_serial_is_ignored(hass: HomeAssistant, mqtt_mock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "mqtt"}, data=_discovery("attacker", serial=SERIAL)
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_pc_on_the_ha_api_is_switched_to_mqtt_only_when_confirmed(hass: HomeAssistant, mqtt_mock) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={CONF_HA_API: True, "device": DEVICE, "apis": {}}
    )
    entry.add_to_hass(hass)

    with patch.object(hass.config_entries, "async_schedule_reload", MagicMock()) as reload:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "mqtt"}, data=_discovery(SERIAL, name="EVIL")
        )

        # Nothing changes until the user confirms.
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "switch_to_mqtt"
        assert entry.title == "MY-PC"
        assert entry.data[CONF_HA_API] is True
        reload.assert_not_called()

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "switched_to_mqtt"
    assert CONF_HA_API not in entry.data
    assert entry.title == "EVIL"
    reload.assert_called_once_with(entry.entry_id)


async def test_pc_on_mqtt_is_updated_as_before(hass: HomeAssistant, mqtt_mock) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={"device": DEVICE, "apis": {}})
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "mqtt"}, data=_discovery(SERIAL)
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# --- events carry the device they came in for --------------------------------------------------

def test_event_names_its_own_device() -> None:
    data = {"action": "unlock_door", "device_name": "OFFICE-PC", "serial_number": "other"}

    own_device(data, "MY-PC", SERIAL)

    assert data == {"action": "unlock_door", "device_name": "MY-PC", "serial_number": SERIAL}


# --- the release notes link -----------------------------------------------------------------------

@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("https://github.com/v1k70rk4/HASS.Agent.NET10/releases/tag/v10.9.1", True),
        ("javascript:alert(1)", False),
        ("https://github.com.evil.example/x", False),
        ("http://github.com/x", False),
        (None, False),
    ],
)
def test_release_link_only_to_github(url, shown: bool) -> None:
    update = HassAgentUpdate.__new__(HassAgentUpdate)
    with patch.object(HassAgentUpdate, "_state", return_value={"release_url": url}):
        assert update.release_url == (url if shown else None)


# --- the local HTTP API -----------------------------------------------------------------------------

async def test_local_api_entry_refuses_another_device(hass: HomeAssistant, mqtt_mock, aioclient_mock) -> None:
    assert await async_setup_component(hass, "http", {})
    url = "http://192.168.1.20:5115"
    aioclient_mock.get(f"{url}/info", json={"serial_number": "ffffffffffffffffffffffffffffffff", "device": DEVICE})
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, title="MY-PC", data={CONF_URL: url})
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


# --- actions find the PC by a name that only one PC has -------------------------------------------

async def test_action_refuses_a_name_two_pcs_have(hass: HomeAssistant, mqtt_mock) -> None:
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    for serial in (SERIAL, "ffffffffffffffffffffffffffffffff"):
        MockConfigEntry(domain=DOMAIN, unique_id=serial, title="KIDS-PC", data={"device": {"name": "KIDS-PC"}}).add_to_hass(hass)

    with pytest.raises(HomeAssistantError, match="more than one"):
        await hass.services.async_call(
            DOMAIN, "execute_command", {"device_name": "KIDS-PC", "command": "shutdown"}, blocking=True
        )
