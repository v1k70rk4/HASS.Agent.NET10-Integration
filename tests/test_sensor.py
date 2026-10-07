"""Custom sensors: what Home Assistant gets for the values a PC reports."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.hass_agent.const import DOMAIN
from custom_components.hass_agent.sensor import HassAgentCustomSensor

DEVICE = SimpleNamespace(
    name="MY-PC",
    identifiers={(DOMAIN, "serial")},
    manufacturer="v1k70rk4",
    model="HASS.Agent .NET10",
    sw_version="10.9.0",
)


def _sensor(**descriptor) -> HassAgentCustomSensor:
    sensor = HassAgentCustomSensor("entry", "serial", DEVICE, {"id": "temp", "name": "CPU temperature", **descriptor})
    sensor.async_write_ha_state = MagicMock()
    return sensor


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (42, 42),
        (3.5, 3.5),
        ("running", "running"),
        (True, "on"),
        (False, "off"),
        (None, None),
    ],
)
def test_value_without_a_unit(value, expected) -> None:
    sensor = _sensor()

    sensor._apply({"value": value})

    assert sensor.native_value == expected
    sensor.async_write_ha_state.assert_called_once()


def test_long_text_is_cut_to_the_state_limit() -> None:
    sensor = _sensor()

    sensor._apply({"value": "x" * 400})

    assert len(sensor.native_value) == 255


def test_value_of_an_unknown_kind_is_skipped() -> None:
    sensor = _sensor()

    sensor._apply({"value": {"nested": 1}})

    sensor.async_write_ha_state.assert_not_called()


@pytest.mark.parametrize("value", ["45.5", "-3", "1e3"])
def test_number_as_text_with_a_unit_is_kept(value) -> None:
    sensor = _sensor(unit="°C")

    sensor._apply({"value": value})

    assert sensor.native_value == value


@pytest.mark.parametrize("value", ["off", "nan", "inf", ""])
def test_text_with_a_unit_becomes_unknown(value) -> None:
    sensor = _sensor(unit="%")

    sensor._apply({"value": value})

    assert sensor.native_value is None


def test_not_numeric_is_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    sensor = _sensor(unit="%")

    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            sensor._apply({"value": "off"})

    warnings = [record for record in caplog.records if "not a number" in record.getMessage()]
    assert len(warnings) == 1
    assert "CPU temperature" in warnings[0].getMessage()


def test_measurement_without_a_unit_also_needs_a_number() -> None:
    sensor = _sensor(state_class="measurement")

    sensor._apply({"value": "busy"})

    assert sensor.native_value is None


def test_attributes_are_taken_only_as_a_mapping() -> None:
    sensor = _sensor()

    sensor._apply({"value": 1, "attributes": {"apps": ["spotify"]}})
    assert sensor.extra_state_attributes == {"apps": ["spotify"]}

    sensor._apply({"value": 1, "attributes": ["not", "a", "mapping"]})
    assert sensor.extra_state_attributes == {}
