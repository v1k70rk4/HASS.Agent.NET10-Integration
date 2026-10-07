"""The actions of the integration and how they check their input."""

from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component

from custom_components.hass_agent.const import DOMAIN


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic timer of its own running after a test."""
    return True


@pytest.fixture
async def integration(hass: HomeAssistant, mqtt_mock):
    """The integration set up with its dependencies (MQTT is a mocked client)."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


async def test_actions_are_registered(hass: HomeAssistant, integration) -> None:
    for action in ("send_notification", "execute_command", "set_app_volume"):
        assert hass.services.has_service(DOMAIN, action)


@pytest.mark.parametrize(
    "data",
    [
        {"device_name": "MY-PC", "command": "format_c"},             # not a command
        {"device_name": "MY-PC", "command": "restart", "time": -1},
        {"command": "restart"},                                       # no device
    ],
)
async def test_execute_command_refuses_bad_input(hass: HomeAssistant, integration, data) -> None:
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await hass.services.async_call(DOMAIN, "execute_command", data, blocking=True)


@pytest.mark.parametrize(
    "data",
    [
        {"device_name": "MY-PC", "app": "spotify", "volume": 101},
        {"device_name": "MY-PC", "app": "spotify", "volume": -1},
        {"device_name": "MY-PC", "volume": 30},                       # no app
    ],
)
async def test_set_app_volume_refuses_bad_input(hass: HomeAssistant, integration, data) -> None:
    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await hass.services.async_call(DOMAIN, "set_app_volume", data, blocking=True)
