"""Sensor platform for HASS.Agent system metrics."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.mqtt.subscription import (
    async_prepare_subscribe_topics,
    async_subscribe_topics,
    async_unsubscribe_topics,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_SENSORS_UPDATED

_LOGGER = logging.getLogger(__name__)


SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cpu-64-bit",
    ),
    SensorEntityDescription(
        key="memory_usage",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:memory",
    ),
    SensorEntityDescription(
        key="memory_available_mb",
        translation_key="memory_available",
        native_unit_of_measurement="MiB",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:memory",
    ),
    SensorEntityDescription(
        key="system_drive_free_percent",
        translation_key="system_drive_free",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:harddisk",
    ),
    SensorEntityDescription(
        key="system_drive_free_gb",
        translation_key="system_drive_free_space",
        native_unit_of_measurement="GiB",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:harddisk",
    ),
    SensorEntityDescription(
        key="uptime_seconds",
        translation_key="uptime",
        native_unit_of_measurement="s",
        device_class=SensorDeviceClass.DURATION,
        icon="mdi:timer-outline",
    ),
    SensorEntityDescription(
        key="active_window",
        translation_key="active_window",
        icon="mdi:application",
    ),
    SensorEntityDescription(
        key="active_process",
        translation_key="active_process",
        icon="mdi:application-brackets",
    ),
    SensorEntityDescription(
        key="foreground_app_title",
        translation_key="foreground_app_title",
        icon="mdi:application-edit",
    ),
    SensorEntityDescription(
        key="volume",
        translation_key="volume",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:volume-high",
    ),
    SensorEntityDescription(
        key="muted",
        translation_key="muted",
        icon="mdi:volume-off",
    ),
    SensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="power_status",
        translation_key="power_status",
        icon="mdi:power-plug",
    ),
    SensorEntityDescription(
        key="monitor_power_state",
        translation_key="monitor_power_state",
        icon="mdi:monitor",
    ),
    SensorEntityDescription(
        key="active_display",
        translation_key="active_display",
        icon="mdi:monitor-multiple",
    ),
    SensorEntityDescription(
        key="network_address",
        translation_key="network_address",
        icon="mdi:ip-network",
    ),
    SensorEntityDescription(
        key="idle_time_seconds",
        translation_key="idle_time",
        native_unit_of_measurement="s",
        device_class=SensorDeviceClass.DURATION,
        icon="mdi:account-clock",
    ),
    SensorEntityDescription(
        key="session_locked",
        translation_key="session_locked",
        icon="mdi:lock-check",
    ),
    SensorEntityDescription(
        key="user_present",
        translation_key="user_present",
        icon="mdi:account-check",
    ),
    SensorEntityDescription(
        key="clipboard_text_available",
        translation_key="clipboard_text_available",
        icon="mdi:clipboard-text",
    ),
    SensorEntityDescription(
        key="session_state",
        translation_key="session_state",
        icon="mdi:account-circle",
    ),
    SensorEntityDescription(
        key="logged_in_user",
        translation_key="logged_in_user",
        icon="mdi:account",
    ),
    SensorEntityDescription(
        key="pending_reboot",
        translation_key="pending_reboot",
        icon="mdi:update",
    ),
    SensorEntityDescription(
        key="windows_update_pending",
        translation_key="windows_update_pending",
        icon="mdi:microsoft-windows",
    ),
    SensorEntityDescription(
        key="bluetooth_enabled",
        translation_key="bluetooth_enabled",
        icon="mdi:bluetooth",
    ),
    SensorEntityDescription(
        key="event_log_errors_recent",
        translation_key="event_log_errors_recent",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-circle",
    ),
    SensorEntityDescription(
        key="last_shutdown_reason",
        translation_key="last_shutdown_reason",
        icon="mdi:power-plug-off",
    ),
    SensorEntityDescription(
        key="boot_time",
        translation_key="boot_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
    ),
    SensorEntityDescription(
        key="battery_time_remaining",
        translation_key="battery_time_remaining",
        native_unit_of_measurement="s",
        device_class=SensorDeviceClass.DURATION,
        icon="mdi:battery-clock",
    ),
    SensorEntityDescription(
        key="vpn_connected",
        translation_key="vpn_connected",
        icon="mdi:vpn",
    ),
    SensorEntityDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        icon="mdi:wifi",
    ),
    SensorEntityDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:wifi-strength-3",
    ),
    SensorEntityDescription(
        key="logged_in_users",
        translation_key="logged_in_users",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:account-multiple",
    ),
    SensorEntityDescription(
        key="rdp_sessions",
        translation_key="rdp_sessions",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:remote-desktop",
    ),
    SensorEntityDescription(
        key="audio_output_device",
        translation_key="audio_output_device",
        icon="mdi:speaker",
    ),
    SensorEntityDescription(
        key="microphone_muted",
        translation_key="microphone_muted",
        icon="mdi:microphone-off",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up HASS.Agent system metric sensors from a config entry."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, entry.unique_id)})

    if device is None:
        return False

    async_add_entities(
        [
            HassAgentSystemSensor(entry.unique_id, device, description)
            for description in SENSOR_DESCRIPTIONS
            if description.key in _standard_sensor_keys(hass, entry)
        ] + [
            HassAgentCustomSensor(entry.entry_id, entry.unique_id, device, sensor)
            for sensor in _custom_sensor_descriptors(hass, entry)
        ]
    )

    return True


def _standard_sensor_keys(hass: HomeAssistant, entry: ConfigEntry) -> set[str]:
    """Return configured standard sensors for this entry."""
    signature = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("standard_sensors", ())
    return set(signature) if isinstance(signature, (tuple, list)) else set()


def _custom_sensor_descriptors(hass: HomeAssistant, entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return configured custom sensors for this entry."""
    signature = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("custom_sensors", ())
    sensors = []
    for item in signature:
        if not isinstance(item, (tuple, list)) or len(item) != 8:
            continue

        sensor_id, sensor_type, name, parameter, unit, device_class, state_class, icon = item
        sensors.append(
            {
                "id": sensor_id,
                "type": sensor_type,
                "name": name,
                "parameter": parameter,
                "unit": unit,
                "device_class": device_class,
                "state_class": state_class,
                "icon": icon,
            }
        )

    return sensors


class HassAgentSystemSensor(SensorEntity):
    """HASS.Agent system metric sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        device: dr.DeviceEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._device_name = device.name
        self._attr_unique_id = f"sensor_{unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers=device.identifiers,
            name=device.name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
        )
        self._listeners: dict[str, Any] = {}
        self._attr_extra_state_attributes = {}

    @callback
    def updated(self, message: ReceiveMessage) -> None:
        """Update the sensor with a new system metrics payload."""
        if not message.payload:
            _LOGGER.debug("received empty system metrics update on '%s', ignoring", message.topic)
            return

        try:
            payload = json.loads(message.payload)
        except ValueError:
            _LOGGER.warning("received invalid system metrics JSON on '%s'", message.topic)
            return

        if not isinstance(payload, dict):
            _LOGGER.warning("received non-object system metrics update on '%s'", message.topic)
            return

        if self.entity_description.key not in payload:
            return

        value = payload.get(self.entity_description.key)
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP and isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return
        elif isinstance(value, bool):
            value = "on" if value else "off"
        elif isinstance(value, str):
            value = value[:255]
        elif value is not None and not isinstance(value, int | float):
            _LOGGER.debug(
                "received unsupported value for %s on '%s'",
                self.entity_description.key,
                message.topic,
            )
            return

        attributes = payload.get("attributes")
        sensor_attributes = attributes.get(self.entity_description.key) if isinstance(attributes, dict) else None
        self._attr_extra_state_attributes = sensor_attributes if isinstance(sensor_attributes, dict) else {}
        self._attr_native_value = value
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to the shared system metrics topic."""
        self._listeners = async_prepare_subscribe_topics(
            self.hass,
            self._listeners,
            {
                f"{self._attr_unique_id}-state": {
                    "topic": f"hass.agent/sensors/{self._device_name}/state",
                    "msg_callback": self.updated,
                    "qos": 0,
                }
            },
        )

        await async_subscribe_topics(self.hass, self._listeners)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from system metrics updates."""
        if self._listeners:
            async_unsubscribe_topics(self.hass, self._listeners)
            self._listeners = {}


class HassAgentCustomSensor(SensorEntity):
    """HASS.Agent user-configured metric sensor."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(
        self,
        entry_id: str,
        unique_id: str,
        device: dr.DeviceEntry,
        descriptor: dict[str, Any],
    ) -> None:
        """Initialize the custom sensor."""
        self._entry_id = entry_id
        self._sensor_id = descriptor["id"]
        self._device_name = device.name
        self._attr_name = descriptor["name"]
        self._attr_unique_id = f"sensor_{unique_id}_custom_{self._sensor_id}"
        self._attr_native_unit_of_measurement = descriptor.get("unit")
        self._attr_icon = descriptor.get("icon")

        if descriptor.get("state_class") == "measurement":
            self._attr_state_class = SensorStateClass.MEASUREMENT

        self._attr_device_info = DeviceInfo(
            identifiers=device.identifiers,
            name=device.name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
        )
        self._listeners: dict[str, Any] = {}
        self._attr_extra_state_attributes = {}

    @callback
    def updated(self, message: ReceiveMessage) -> None:
        """Update the custom sensor with a new system metrics payload."""
        if not message.payload:
            return

        try:
            payload = json.loads(message.payload)
        except ValueError:
            _LOGGER.warning("received invalid system metrics JSON on '%s'", message.topic)
            return

        if not isinstance(payload, dict):
            return

        custom_sensors = payload.get("custom_sensors")
        if not isinstance(custom_sensors, list):
            return

        for sensor in custom_sensors:
            if not isinstance(sensor, dict) or sensor.get("id") != self._sensor_id:
                continue

            value = sensor.get("value")
            if isinstance(value, bool):
                value = "on" if value else "off"
            elif isinstance(value, str):
                value = value[:255]
            elif value is not None and not isinstance(value, int | float):
                return

            attributes = sensor.get("attributes")
            self._attr_extra_state_attributes = attributes if isinstance(attributes, dict) else {}
            self._attr_native_value = value
            self.async_write_ha_state()
            return

    async def async_added_to_hass(self) -> None:
        """Subscribe to the shared system metrics topic."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SENSORS_UPDATED.format(self._entry_id),
                self.async_write_ha_state,
            )
        )
        self._listeners = async_prepare_subscribe_topics(
            self.hass,
            self._listeners,
            {
                f"{self._attr_unique_id}-state": {
                    "topic": f"hass.agent/sensors/{self._device_name}/state",
                    "msg_callback": self.updated,
                    "qos": 0,
                }
            },
        )

        await async_subscribe_topics(self.hass, self._listeners)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from system metrics updates."""
        if self._listeners:
            async_unsubscribe_topics(self.hass, self._listeners)
            self._listeners = {}
