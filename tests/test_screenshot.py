"""The screenshot a PC takes when it is asked to: the button, and the image it fills."""

from __future__ import annotations

import base64
from http import HTTPStatus

import pytest
from homeassistant.const import MATCH_ALL, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_mqtt_message,
)

from custom_components.hass_agent import handle_apis_changed
from custom_components.hass_agent.const import (
    CONF_HA_API,
    CONF_USER_ID,
    DOMAIN,
    MAX_SCREENSHOT_BYTES,
)

SERIAL = "0123456789abcdef0123456789abcdef"
OTHER = "ffffffffffffffffffffffffffffffff"
DEVICE = {"name": "MY-PC", "manufacturer": "v1k70rk4", "model": "HASS.Agent .NET10", "sw_version": "10.14.0"}
TOPIC = f"hass.agent/screenshot/{SERIAL}/image"

# Enough of each to be told as a whole picture: how it begins and how it ends. Nothing
# decodes what is in between.
JPEG = b"\xff\xd8\xff\xe0" + b"a jpeg of the screen" + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"a png of the screen" + b"\x00\x00\x00\x00IEND\xaeB`\x82"


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


def _apis(*commands: str) -> dict:
    return {
        "buttons": bool(commands),
        "commands": [{"name": name, "display_name": name.capitalize()} for name in commands],
    }


async def _pc(
    hass: HomeAssistant, *commands: str, ha_api: bool = False, serial: str = SERIAL, user_id: str | None = None
) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    data: dict = {"device": DEVICE, "apis": {}}
    if ha_api:
        data[CONF_HA_API] = True
    if user_id is not None:
        data[CONF_USER_ID] = user_id
    entry = MockConfigEntry(domain=DOMAIN, unique_id=serial, title="MY-PC", data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, serial)}, name="MY-PC"
    )
    await handle_apis_changed(hass, entry, _apis(*commands))
    await hass.async_block_till_done()
    return entry


def _entity_id(hass: HomeAssistant, domain: str, serial: str = SERIAL) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{domain}_{serial}_screenshot")


async def _picture(hass: HomeAssistant, hass_client, entity_id: str) -> tuple[int, str | None, bytes]:
    client = await hass_client()
    response = await client.get(f"/api/image_proxy/{entity_id}")
    return response.status, response.headers.get("Content-Type"), await response.read()


async def test_the_command_brings_a_button_and_an_image(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await _pc(hass, "lock", "screenshot")

    assert _entity_id(hass, "button") is not None
    image = _entity_id(hass, "image")
    assert image is not None
    # Nothing was asked for yet: there is no picture to show.
    assert hass.states.get(image).state == STATE_UNKNOWN

    # Unticked on the PC, both go.
    await handle_apis_changed(hass, entry, _apis("lock"))
    await hass.async_block_till_done()
    assert _entity_id(hass, "button") is None
    assert _entity_id(hass, "image") is None


async def test_a_pc_without_the_command_has_no_image(hass: HomeAssistant, mqtt_mock) -> None:
    await _pc(hass, "lock")

    assert _entity_id(hass, "image") is None


async def test_a_screenshot_over_mqtt_is_the_picture_of_the_image(hass: HomeAssistant, mqtt_mock, hass_client) -> None:
    await _pc(hass, "screenshot")
    image = _entity_id(hass, "image")

    async_fire_mqtt_message(hass, TOPIC, JPEG)
    await hass.async_block_till_done()

    first = hass.states.get(image).state
    assert first != STATE_UNKNOWN
    assert await _picture(hass, hass_client, image) == (HTTPStatus.OK, "image/jpeg", JPEG)

    # The next one replaces it, and is told by its own bytes.
    async_fire_mqtt_message(hass, TOPIC, PNG)
    await hass.async_block_till_done()
    assert await _picture(hass, hass_client, image) == (HTTPStatus.OK, "image/png", PNG)


@pytest.mark.parametrize(
    "payload",
    [
        b"not a picture at all",
        b"<html><script>alert(1)</script></html>",
        b"\xff\xd8\xff" + b"0" * MAX_SCREENSHOT_BYTES + b"\xff\xd9",
        b"\xff\xd8\xff",
        JPEG[:-2],
        PNG[:-12],
        b"\xff\xd8\xff\xd9",
    ],
    ids=[
        "text",
        "html",
        "too large",
        "only the start of a jpeg",
        "a jpeg cut off",
        "a png cut off",
        "a jpeg with nothing in it",
    ],
)
async def test_what_is_not_a_picture_is_not_taken(hass: HomeAssistant, mqtt_mock, payload: bytes) -> None:
    await _pc(hass, "screenshot")
    image = _entity_id(hass, "image")

    async_fire_mqtt_message(hass, TOPIC, payload)
    await hass.async_block_till_done()

    assert hass.states.get(image).state == STATE_UNKNOWN


async def test_a_bad_picture_leaves_the_last_good_one(hass: HomeAssistant, mqtt_mock, hass_client) -> None:
    await _pc(hass, "screenshot")
    image = _entity_id(hass, "image")
    async_fire_mqtt_message(hass, TOPIC, JPEG)
    await hass.async_block_till_done()

    taken = hass.states.get(image).state
    for bad in (b"not a picture at all", b"\xff\xd8\xff", JPEG[:-2]):
        async_fire_mqtt_message(hass, TOPIC, bad)
        await hass.async_block_till_done()

    # The picture, and the time it was taken, are those of the last good one.
    assert await _picture(hass, hass_client, image) == (HTTPStatus.OK, "image/jpeg", JPEG)
    assert hass.states.get(image).state == taken


async def _user_client(hass, hass_ws_client, name: str):
    user = await hass.auth.async_create_user(name, group_ids=["system-users"])
    refresh = await hass.auth.async_create_refresh_token(user, "https://example.com/")
    token = hass.auth.async_create_access_token(refresh)
    return await hass_ws_client(hass, access_token=token), user


async def _send(client, serial: str, image: str) -> dict:
    await client.send_json_auto_id({"type": "hass_agent/screenshot", "serial_number": serial, "image": image})
    return await client.receive_json()


async def test_a_screenshot_over_the_ha_api_goes_to_the_image_and_not_on_the_bus(
    hass: HomeAssistant, mqtt_mock, hass_ws_client, hass_client
) -> None:
    client, user = await _user_client(hass, hass_ws_client, "pc-user")
    await _pc(hass, "screenshot", ha_api=True, user_id=user.id)
    image = _entity_id(hass, "image")
    events = async_capture_events(hass, MATCH_ALL)

    result = await _send(client, SERIAL, base64.b64encode(JPEG).decode())
    await hass.async_block_till_done()

    assert result["success"]
    assert await _picture(hass, hass_client, image) == (HTTPStatus.OK, "image/jpeg", JPEG)
    # The picture went to the entity alone: no event carries it. What is on the bus is the
    # entity's new state, which is a time.
    encoded = base64.b64encode(JPEG).decode()
    assert all(encoded not in str(event.data) for event in events)
    assert {event.event_type for event in events} <= {"state_changed"}


async def test_a_pc_cannot_send_a_screenshot_for_another_pc(hass: HomeAssistant, mqtt_mock, hass_ws_client) -> None:
    client, user = await _user_client(hass, hass_ws_client, "pc-user")
    await _pc(hass, "screenshot", ha_api=True, user_id=user.id)
    await _pc(hass, "screenshot", ha_api=True, serial=OTHER, user_id="someone-else")

    result = await _send(client, OTHER, base64.b64encode(JPEG).decode())
    await hass.async_block_till_done()

    assert result["error"]["code"] == "unauthorized"
    assert hass.states.get(_entity_id(hass, "image", OTHER)).state == STATE_UNKNOWN


@pytest.mark.parametrize(
    "image",
    ["not base64 !!", "A" * (MAX_SCREENSHOT_BYTES * 4 // 3 + 8)],
    ids=["not base64", "too large"],
)
async def test_a_screenshot_that_cannot_be_read_is_refused(
    hass: HomeAssistant, mqtt_mock, hass_ws_client, image: str
) -> None:
    client, user = await _user_client(hass, hass_ws_client, "pc-user")
    await _pc(hass, "screenshot", ha_api=True, user_id=user.id)

    result = await _send(client, SERIAL, image)

    assert result["error"]["code"] == "invalid_format"
    assert hass.states.get(_entity_id(hass, "image")).state == STATE_UNKNOWN
