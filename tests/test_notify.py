"""Notifications: the fields of the action, the picture of a notification, the transports."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.hass_agent.const import CONF_HA_API, DOMAIN
from custom_components.hass_agent.notify import HassAgentNotifyEntity, _prepare_image

SERIAL = "0123456789abcdef0123456789abcdef"


def _fake_sign(_hass, path, _lifetime, use_content_user=False):
    assert use_content_user
    return f"{path}?authSig=signed"


@pytest.fixture
def signing():
    """Signing needs the http component's secret; the address it produces is what matters here."""
    with patch("custom_components.hass_agent.notify.async_sign_path", side_effect=_fake_sign):
        yield


async def _set_urls(hass: HomeAssistant, internal: str | None, external: str | None) -> None:
    await hass.config.async_update(internal_url=internal, external_url=external)


# --- _prepare_image ------------------------------------------------------------------------

async def test_web_address_is_passed_on_untouched(hass: HomeAssistant, signing) -> None:
    data = {"image": "https://example.com/doorbell.jpg"}

    assert _prepare_image(hass, data) == data


@pytest.mark.parametrize(
    ("image", "path"),
    [
        ("camera.front_door", "/api/camera_proxy/camera.front_door"),
        ("image.doorbell_snapshot", "/api/image_proxy/image.doorbell_snapshot"),
        ("/local/doorbell.jpg", "/local/doorbell.jpg"),
        ("  /local/doorbell.jpg  ", "/local/doorbell.jpg"),
    ],
)
async def test_picture_on_home_assistant_is_signed(hass: HomeAssistant, signing, image: str, path: str) -> None:
    await _set_urls(hass, "http://192.168.1.10:8123", "https://ha.example.com")

    prepared = _prepare_image(hass, {"image": image, "style": "window"})

    assert prepared["image_path"] == f"{path}?authSig=signed"
    assert prepared["image"] == f"http://192.168.1.10:8123{path}?authSig=signed"
    assert prepared["image_alt"] == f"https://ha.example.com{path}?authSig=signed"
    assert prepared["style"] == "window"


async def test_only_one_address_known(hass: HomeAssistant, signing) -> None:
    await _set_urls(hass, None, "https://ha.example.com")

    prepared = _prepare_image(hass, {"image": "/local/a.jpg"})

    assert prepared["image"] == "https://ha.example.com/local/a.jpg?authSig=signed"
    assert "image_alt" not in prepared


async def test_original_data_is_not_changed(hass: HomeAssistant, signing) -> None:
    data = {"image": "camera.front_door"}

    _prepare_image(hass, data)

    assert data == {"image": "camera.front_door"}


@pytest.mark.parametrize("image", [None, 42, ["camera.x"], "switch.not_a_picture"])
async def test_no_picture_or_not_a_picture(hass: HomeAssistant, signing, image) -> None:
    data = {"image": image}

    assert _prepare_image(hass, data) == data


# --- sending -------------------------------------------------------------------------------

def _entity(hass: HomeAssistant, **entry_data) -> HassAgentNotifyEntity:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data=entry_data, title="MY-PC")
    entry.add_to_hass(hass)
    entity = HassAgentNotifyEntity(hass, entry, "MY-PC", "MY-PC")
    entity.hass = hass
    return entity


async def test_fields_of_their_own_win_over_data(hass: HomeAssistant, signing) -> None:
    entity = _entity(hass, **{CONF_HA_API: True})
    events = async_capture_events(hass, "hass_agent_command")

    await entity.async_send_hass_agent_notification(
        "Somebody is at the door",
        None,
        {"style": "toast", "duration": 5, "actions": [{"action": "old", "title": "Old"}]},
        style="window",
        actions=[{"action": "open", "title": "Open"}],
        duration=None,           # not given in the action: the value in data stays
        unknown_field="ignored",
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    payload = events[0].data["payload"]
    assert events[0].data["serial_number"] == SERIAL
    assert events[0].data["command_type"] == "notification"
    assert payload["message"] == "Somebody is at the door"
    assert payload["title"] == "Home Assistant"
    assert payload["data"] == {"style": "window", "duration": 5, "actions": [{"action": "open", "title": "Open"}]}


async def test_ha_api_only_pc_gets_no_mqtt_message(hass: HomeAssistant, signing) -> None:
    entity = _entity(hass, **{CONF_HA_API: True})

    with patch("custom_components.hass_agent.notify.mqtt.async_publish", new=AsyncMock()) as publish:
        await entity.async_send_hass_agent_notification("Hello")

    publish.assert_not_called()


async def test_mqtt_pc_gets_the_notification_on_its_topic_and_the_bus(hass: HomeAssistant, signing) -> None:
    entity = _entity(hass)
    events = async_capture_events(hass, "hass_agent_command")

    with patch("custom_components.hass_agent.notify.mqtt.async_publish", new=AsyncMock()) as publish:
        await entity.async_send_hass_agent_notification("Hello", "Title", image="camera.front_door")
    await hass.async_block_till_done()

    publish.assert_awaited_once()
    _, topic, raw = publish.await_args.args[:3]
    assert topic == f"hass.agent/notifications/{SERIAL}"
    sent = json.loads(raw)
    assert sent["title"] == "Title"
    assert sent["data"]["image_path"] == "/api/camera_proxy/camera.front_door?authSig=signed"
    assert publish.await_args.kwargs == {"qos": 0, "retain": False}
    # The bus carries it too, for a PC that is on the HA API at the moment.
    assert len(events) == 1
