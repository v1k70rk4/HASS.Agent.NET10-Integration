"""The HASS.Agent integration."""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import ClientError, ClientTimeout

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.components.notify.const import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TITLE,
    DOMAIN as NOTIFY_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.mqtt.subscription import (
    async_prepare_subscribe_topics,
    async_subscribe_topics,
    async_unsubscribe_topics,
)
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.issue_registry import async_delete_issue
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_COMMENT,
    CONF_COMMAND,
    CONF_DEVICE_NAME,
    CONF_FORCE,
    CONF_RESTART_CANCEL,
    CONF_TIME,
    DOMAIN,
    SIGNAL_BUTTONS_UPDATED,
    SIGNAL_SENSORS_UPDATED,
)

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.EVENT,
    Platform.SENSOR,
    Platform.BUTTON,
]
SERVICE_SEND_NOTIFICATION = "send_notification"
SERVICE_EXECUTE_COMMAND = "execute_command"
SERVICE_STATUS_STORAGE_KEY = "_service_status"
BUTTON_COMMANDS_STORAGE_KEY = "button_commands"
CUSTOM_SENSORS_STORAGE_KEY = "custom_sensors"
STANDARD_SENSORS_STORAGE_KEY = "standard_sensors"
SYSTEM_COMMANDS = {
    "lock",
    "sleep",
    "monitor_off",
    "volume_up",
    "volume_down",
    "toggle_mute",
    "shutdown",
    "restart",
}
SYSTEM_SERVICE_COMMANDS = {"shutdown", "restart", "restart_cancel"}
BUTTON_ENTITY_COMMANDS = SYSTEM_COMMANDS | {"restart_cancel"}

_logger = logging.getLogger(__name__)


def update_device_info(
    hass: HomeAssistant,
    entry: ConfigEntry,
    new_device_info: dict[str, Any],
) -> None:
    """Update the Home Assistant device registry from HASS.Agent device data."""
    device_info = new_device_info.get("device")
    if not isinstance(device_info, dict):
        _logger.debug("received device update without device info for %s", entry.unique_id)
        return

    device_name = device_info.get("name")
    if not isinstance(device_name, str) or not device_name:
        _logger.debug("received device update without device name for %s", entry.unique_id)
        return

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id)},
        name=device_name,
        manufacturer=device_info.get("manufacturer"),
        model=device_info.get("model"),
        sw_version=device_info.get("sw_version"),
    )


async def _async_update_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    platform: Platform,
    loaded_key: str,
    should_load: bool,
    device_name: str,
) -> None:
    """Load or unload a platform when a HASS.Agent API capability changes."""
    loaded = hass.data[DOMAIN][entry.entry_id]["loaded"]
    is_loaded = loaded.get(loaded_key, False)

    if should_load and not is_loaded:
        _logger.debug("loading %s for device: %s [%s]", platform, device_name, entry.unique_id)
        await hass.config_entries.async_forward_entry_setups(entry, [platform])
        loaded[loaded_key] = True
        return

    if not should_load and is_loaded:
        _logger.debug("unloading %s for device: %s [%s]", platform, device_name, entry.unique_id)
        unload_ok = await hass.config_entries.async_forward_entry_unload(entry, platform)
        if unload_ok:
            loaded[loaded_key] = False
            _async_remove_platform_entities(hass, entry, platform)
        else:
            _logger.warning("failed to unload %s for device: %s [%s]", platform, device_name, entry.unique_id)
    elif not should_load:
        _async_remove_platform_entities(hass, entry, platform)


def _async_remove_platform_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    platform: Platform,
) -> None:
    """Remove all entities for a disabled simple platform from the entity registry."""
    entity_registry = er.async_get(hass)
    for entity in list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)):
        if entity.domain == platform.value:
            entity_registry.async_remove(entity.entity_id)


def _normalize_commands(commands: Any) -> tuple[tuple[str, str, str | None], ...]:
    """Return a stable command descriptor tuple from a HASS.Agent command list."""
    if not isinstance(commands, list):
        return ()

    normalized: dict[str, tuple[str, str | None]] = {}
    for command in commands:
        if not isinstance(command, dict) or not isinstance(command.get("name"), str):
            continue

        display_name = command.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            continue

        comment = command.get("comment")
        normalized[command["name"]] = (
            display_name.strip(),
            comment.strip() if isinstance(comment, str) and comment.strip() else None,
        )

    return tuple(
        (name, display_name, comment)
        for name, (display_name, comment) in sorted(normalized.items(), key=lambda item: item[0])
    )


def _available_button_commands(apis: dict[str, Any], service_status: dict[str, Any]) -> tuple[tuple[str, str, str | None], ...]:
    """Return commands currently handled by either the tray app or the system service."""
    commands: dict[str, tuple[str, str | None]] = {}

    if apis.get("buttons") is True:
        commands.update({command[0]: (command[1], command[2]) for command in _normalize_commands(apis.get("commands"))})

    if service_status.get("online") is True:
        commands.update({command[0]: (command[1], command[2]) for command in _normalize_commands(service_status.get("commands"))})

    return tuple(
        (name, display_name, comment)
        for name, (display_name, comment) in sorted(commands.items(), key=lambda item: item[0])
    )


def _normalize_custom_sensors(sensors: Any) -> tuple[tuple[str, str, str, str, str | None, str | None, str | None, str | None], ...]:
    """Return a stable tuple of custom sensor descriptors."""
    if not isinstance(sensors, list):
        return ()

    normalized = []
    for sensor in sensors:
        if not isinstance(sensor, dict):
            continue

        sensor_id = sensor.get("id")
        sensor_type = sensor.get("type")
        name = sensor.get("name")
        parameter = sensor.get("parameter")
        if not all(isinstance(value, str) and value for value in (sensor_id, sensor_type, name, parameter)):
            continue

        normalized.append(
            (
                sensor_id,
                sensor_type,
                name,
                parameter,
                sensor.get("unit") if isinstance(sensor.get("unit"), str) else None,
                sensor.get("device_class") if isinstance(sensor.get("device_class"), str) else None,
                sensor.get("state_class") if isinstance(sensor.get("state_class"), str) else None,
                sensor.get("icon") if isinstance(sensor.get("icon"), str) else None,
            )
        )

    return tuple(sorted(normalized, key=lambda item: item[0]))


def _normalize_standard_sensors(sensors: Any) -> tuple[tuple[str, str], ...]:
    """Return a stable tuple of standard sensor descriptors."""
    if not isinstance(sensors, list):
        return ()

    normalized: dict[str, str] = {}
    for sensor in sensors:
        if not isinstance(sensor, dict) or not isinstance(sensor.get("key"), str):
            continue

        name = sensor.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        normalized[sensor["key"]] = name.strip()

    return tuple(sorted(normalized.items(), key=lambda item: item[0]))


def _available_standard_sensors(apis: dict[str, Any], service_status: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Return standard sensors currently handled by either app or service."""
    sensors = (
        dict(_normalize_standard_sensors(apis.get("standard_sensors")))
        if apis.get("system_sensors") is True
        else {}
    )

    if service_status.get("online") is True and service_status.get("system_sensors") is True:
        sensors.update(dict(_normalize_standard_sensors(service_status.get("standard_sensors"))))

    return tuple(sorted(sensors.items(), key=lambda item: item[0]))


def _available_custom_sensors(apis: dict[str, Any], service_status: dict[str, Any]) -> tuple[tuple[str, str, str, str, str | None, str | None, str | None, str | None], ...]:
    """Return custom sensors currently handled by either app or service."""
    sensors: dict[str, tuple[str, str, str, str, str | None, str | None, str | None, str | None]] = {}

    if apis.get("system_sensors") is True:
        for sensor in _normalize_custom_sensors(apis.get("custom_sensors")):
            sensors[sensor[0]] = sensor

    if service_status.get("online") is True and service_status.get("system_sensors") is True:
        for sensor in _normalize_custom_sensors(service_status.get("custom_sensors")):
            sensors[sensor[0]] = sensor

    return tuple(sorted(sensors.values(), key=lambda item: item[0]))


def _button_update_signal(entry_id: str) -> str:
    """Return the dispatcher signal for button state updates."""
    return SIGNAL_BUTTONS_UPDATED.format(entry_id)


def _button_unique_id(entry: ConfigEntry, command: str) -> str:
    """Return the unique ID used by the command button entity."""
    return f"button_{entry.unique_id}_{command}"


def _sensor_unique_id(entry: ConfigEntry, sensor_id: str) -> str:
    """Return the unique ID used by a custom sensor entity."""
    return f"sensor_{entry.unique_id}_custom_{sensor_id}"


def _standard_sensor_unique_id(entry: ConfigEntry, sensor_key: str) -> str:
    """Return the unique ID used by a standard sensor entity."""
    return f"sensor_{entry.unique_id}_{sensor_key}"


def _async_remove_inactive_button_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    active_commands: set[str],
) -> None:
    """Remove disabled command button entities from the entity registry."""
    entity_registry = er.async_get(hass)

    for command in BUTTON_ENTITY_COMMANDS - active_commands:
        entity_id = entity_registry.async_get_entity_id(
            Platform.BUTTON.value,
            DOMAIN,
            _button_unique_id(entry, command),
        )
        if entity_id is not None:
            entity_registry.async_remove(entity_id)


def _async_remove_inactive_custom_sensor_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    active_sensor_ids: set[str],
) -> None:
    """Remove disabled custom sensor entities from the entity registry."""
    entity_registry = er.async_get(hass)

    for entity in list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)):
        if entity.domain != Platform.SENSOR.value or not entity.unique_id.startswith(f"sensor_{entry.unique_id}_custom_"):
            continue

        sensor_id = entity.unique_id.removeprefix(f"sensor_{entry.unique_id}_custom_")
        if sensor_id not in active_sensor_ids:
            entity_registry.async_remove(entity.entity_id)


def _async_remove_inactive_standard_sensor_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    active_sensor_keys: set[str],
) -> None:
    """Remove disabled standard sensor entities from the entity registry."""
    entity_registry = er.async_get(hass)

    for entity in list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)):
        if entity.domain != Platform.SENSOR.value:
            continue
        if entity.unique_id.startswith(f"sensor_{entry.unique_id}_custom_"):
            continue
        if not entity.unique_id.startswith(f"sensor_{entry.unique_id}_"):
            continue

        sensor_key = entity.unique_id.removeprefix(f"sensor_{entry.unique_id}_")
        if sensor_key not in active_sensor_keys:
            entity_registry.async_remove(entity.entity_id)


async def _async_update_button_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    should_load: bool,
    device_name: str,
    command_signature: tuple[tuple[str, str, str | None], ...],
) -> None:
    """Load, unload, or reload button entities when the command list changes."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    loaded = entry_data["loaded"]
    is_loaded = loaded.get("button", False)
    previous_signature = tuple(entry_data.get(BUTTON_COMMANDS_STORAGE_KEY, ()))
    active_commands = {command[0] for command in command_signature}

    if should_load and is_loaded and previous_signature == command_signature:
        _async_remove_inactive_button_entities(hass, entry, active_commands)
        return

    if is_loaded:
        _logger.debug("unloading button for device: %s [%s]", device_name, entry.unique_id)
        unload_ok = await hass.config_entries.async_forward_entry_unload(entry, Platform.BUTTON)
        if not unload_ok:
            _logger.warning("failed to unload button for device: %s [%s]", device_name, entry.unique_id)
            return

        loaded["button"] = False
        await hass.async_block_till_done()

    _async_remove_inactive_button_entities(hass, entry, active_commands)
    entry_data[BUTTON_COMMANDS_STORAGE_KEY] = command_signature

    if should_load:
        _logger.debug(
            "loading button for device: %s [%s] commands=%s",
            device_name,
            entry.unique_id,
            command_signature,
        )
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.BUTTON])
        loaded["button"] = True


async def _async_update_sensor_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    should_load: bool,
    device_name: str,
    custom_sensors: tuple[tuple[str, str, str, str, str | None, str | None, str | None, str | None], ...],
    standard_sensors: tuple[tuple[str, str], ...],
) -> None:
    """Load, unload, or reload sensor entities when custom sensors change."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    loaded = entry_data["loaded"]
    is_loaded = loaded.get("sensor", False)
    previous_custom_signature = tuple(entry_data.get(CUSTOM_SENSORS_STORAGE_KEY, ()))
    previous_standard_signature = tuple(entry_data.get(STANDARD_SENSORS_STORAGE_KEY, ()))
    active_sensor_ids = {sensor[0] for sensor in custom_sensors}
    active_standard_keys = {sensor[0] for sensor in standard_sensors}

    if should_load and is_loaded and previous_custom_signature == custom_sensors and previous_standard_signature == standard_sensors:
        _async_remove_inactive_custom_sensor_entities(hass, entry, active_sensor_ids)
        _async_remove_inactive_standard_sensor_entities(hass, entry, active_standard_keys)
        async_dispatcher_send(hass, SIGNAL_SENSORS_UPDATED.format(entry.entry_id))
        return

    if is_loaded:
        _logger.debug("unloading sensor for device: %s [%s]", device_name, entry.unique_id)
        unload_ok = await hass.config_entries.async_forward_entry_unload(entry, Platform.SENSOR)
        if not unload_ok:
            _logger.warning("failed to unload sensor for device: %s [%s]", device_name, entry.unique_id)
            return

        loaded["sensor"] = False
        await hass.async_block_till_done()

    _async_remove_inactive_custom_sensor_entities(hass, entry, active_sensor_ids)
    _async_remove_inactive_standard_sensor_entities(hass, entry, active_standard_keys)
    entry_data[CUSTOM_SENSORS_STORAGE_KEY] = custom_sensors
    entry_data[STANDARD_SENSORS_STORAGE_KEY] = standard_sensors

    if should_load:
        _logger.debug("loading sensor for device: %s [%s]", device_name, entry.unique_id)
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
        loaded["sensor"] = True


async def handle_apis_changed(
    hass: HomeAssistant,
    entry: ConfigEntry,
    apis: dict[str, Any] | None,
) -> None:
    _logger.debug("api changed for: %s", entry.unique_id)
    if apis is not None:
        if not isinstance(apis, dict):
            _logger.warning("received invalid API capabilities for %s", entry.unique_id)
            return

        device_registry = dr.async_get(hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, entry.unique_id)})
        device_name = device.name if device is not None else entry.title

        media_player = apis.get("media_player", False)
        notifications = apis.get("notifications", False)
        notification_events = notifications and entry.data.get(CONF_URL) is None
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        service_status = entry_data.get("service", {})
        if not isinstance(service_status, dict):
            service_status = {}
        system_sensors = (
            apis.get("system_sensors", False)
            or (service_status.get("online") is True and service_status.get("system_sensors") is True)
        ) and entry.data.get(CONF_URL) is None
        custom_sensors = _available_custom_sensors(apis, service_status)
        standard_sensors = _available_standard_sensors(apis, service_status)
        button_commands = _available_button_commands(apis, service_status)
        buttons = bool(button_commands) and entry.data.get(CONF_URL) is None

        await _async_update_platform(
            hass,
            entry,
            Platform.MEDIA_PLAYER,
            "media_player",
            bool(media_player),
            device_name,
        )
        await _async_update_platform(
            hass,
            entry,
            Platform.NOTIFY,
            "notifications",
            bool(notifications),
            device_name,
        )
        await _async_update_platform(
            hass,
            entry,
            Platform.EVENT,
            "event",
            bool(notification_events),
            device_name,
        )
        await _async_update_sensor_platform(
            hass,
            entry,
            bool(system_sensors),
            device_name,
            custom_sensors,
            standard_sensors,
        )
        await _async_update_button_platform(
            hass,
            entry,
            bool(buttons),
            device_name,
            button_commands,
        )
        async_dispatcher_send(hass, _button_update_signal(entry.entry_id))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HASS.Agent from a config entry."""

    _logger.debug("setting up device from config entry: %s [%s]", entry.title, entry.unique_id)

    hass.data.setdefault(DOMAIN, {})

    hass.data[DOMAIN].setdefault(
        entry.entry_id,
        {
            "internal_mqtt": {},
            "apis": {},
            "service": {},
            BUTTON_COMMANDS_STORAGE_KEY: (),
            CUSTOM_SENSORS_STORAGE_KEY: (),
            STANDARD_SENSORS_STORAGE_KEY: (),
            "thumbnail": None,
            "loaded": {
                "media_player": False,
                "notifications": False,
                "event": False,
                "sensor": False,
                "button": False,
            },
        },
    )

    url = entry.data.get(CONF_URL, None)

    if url is not None:
        session = async_get_clientsession(hass)
        try:
            async with session.get(
                f"{url}/info", timeout=ClientTimeout(total=60)
            ) as response:
                response.raise_for_status()
                response_json = await response.json()
        except (ClientError, TimeoutError) as ex:
            raise ConfigEntryNotReady(f"Failed to connect to HASS.Agent at {url}") from ex

        if not isinstance(response_json, dict):
            raise ConfigEntryNotReady(f"Received invalid HASS.Agent info response from {url}")

        update_device_info(hass, entry, response_json)

        apis = {
            "notifications": True,
            "media_player": False,  # unsupported for the moment
            "buttons": False,
            "system_sensors": False,
        }

        await handle_apis_changed(hass, entry, apis)
        hass.data[DOMAIN][entry.entry_id]["apis"] = apis

    else:
        device_name = entry.data["device"]["name"]

        sub_state = hass.data[DOMAIN][entry.entry_id]["internal_mqtt"]

        @callback
        def updated(message: ReceiveMessage) -> None:
            if not message.payload:
                _logger.debug("received empty update message on '%s', ignoring", message.topic)
                return

            try:
                payload = json.loads(message.payload)
            except ValueError:
                _logger.warning("received invalid JSON update on '%s'", message.topic)
                return

            if not isinstance(payload, dict):
                _logger.warning("received non-object update on '%s'", message.topic)
                return

            cached = hass.data[DOMAIN][entry.entry_id]["apis"]
            apis = payload.get("apis")
            if not isinstance(apis, dict):
                _logger.warning("received update without API capabilities on '%s'", message.topic)
                return

            update_device_info(hass, entry, payload)

            hass.data[DOMAIN][entry.entry_id]["apis"] = apis
            if cached != apis:
                hass.async_create_background_task(handle_apis_changed(hass, entry, apis), "hass.agent-mqtt")
            else:
                hass.async_create_background_task(handle_apis_changed(hass, entry, apis), "hass.agent-mqtt-refresh")

        @callback
        def service_updated(message: ReceiveMessage) -> None:
            if not message.payload:
                _logger.debug("received empty service update on '%s', ignoring", message.topic)
                return

            try:
                payload = json.loads(message.payload)
            except ValueError:
                _logger.warning("received invalid service JSON on '%s'", message.topic)
                return

            if not isinstance(payload, dict):
                _logger.warning("received non-object service update on '%s'", message.topic)
                return

            entry_data = hass.data[DOMAIN][entry.entry_id]
            previous_online = bool(entry_data.get("service", {}).get("online"))
            previous_commands = _normalize_commands(entry_data.get("service", {}).get("commands"))
            previous_system_sensors = bool(entry_data.get("service", {}).get("system_sensors"))
            previous_custom_sensors = _normalize_custom_sensors(entry_data.get("service", {}).get("custom_sensors"))
            previous_standard_sensors = _normalize_standard_sensors(entry_data.get("service", {}).get("standard_sensors"))
            entry_data["service"] = payload
            hass.data[DOMAIN].setdefault(SERVICE_STATUS_STORAGE_KEY, {})[device_name] = payload

            online = payload.get("online") is True
            commands = _normalize_commands(payload.get("commands"))
            system_sensors = payload.get("system_sensors") is True
            custom_sensors = _normalize_custom_sensors(payload.get("custom_sensors"))
            standard_sensors = _normalize_standard_sensors(payload.get("standard_sensors"))
            if (
                previous_online != online
                or previous_commands != commands
                or previous_system_sensors != system_sensors
                or previous_custom_sensors != custom_sensors
                or previous_standard_sensors != standard_sensors
            ):
                cached_apis = entry_data.get("apis", {})
                hass.async_create_background_task(
                    handle_apis_changed(hass, entry, cached_apis),
                    "hass.agent-service",
                )

        sub_state = async_prepare_subscribe_topics(
            hass,
            sub_state,
            {
                f"{entry.unique_id}-apis": {
                    "topic": f"hass.agent/devices/{device_name}",
                    "msg_callback": updated,
                    "qos": 0,
                },
                f"{entry.unique_id}-service": {
                    "topic": f"hass.agent/system/{device_name}/state",
                    "msg_callback": service_updated,
                    "qos": 0,
                },
            },
        )

        await async_subscribe_topics(hass, sub_state)

        hass.data[DOMAIN][entry.entry_id]["internal_mqtt"] = sub_state

    # Clean up stale restart_required repair issues for this device.
    # These are created on device rename and resolved by any HA restart,
    # but the repair flow may not persist the resolution before shutdown.
    async_delete_issue(hass, DOMAIN, f"restart_required_{entry.title}")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    _logger.debug("unloading device: %s [%s]", entry.title, entry.unique_id)

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        _logger.debug("config entry (%s) has no runtime data to unload", entry.unique_id)
        return True

    loaded = entry_data.get("loaded", None)

    if loaded is not None:
        platforms_to_unload = []

        if loaded.get("media_player", False):
            platforms_to_unload.append(Platform.MEDIA_PLAYER)

        if loaded.get("notifications", False):
            platforms_to_unload.append(Platform.NOTIFY)

        if loaded.get("event", False):
            platforms_to_unload.append(Platform.EVENT)

        if loaded.get("sensor", False):
            platforms_to_unload.append(Platform.SENSOR)

        if loaded.get("button", False):
            platforms_to_unload.append(Platform.BUTTON)

        if platforms_to_unload:
            unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms_to_unload)
            if unload_ok:
                _logger.debug("unloaded platforms %s for: %s [%s]", platforms_to_unload, entry.title, entry.unique_id)
            else:
                _logger.warning("failed to unload platforms %s for: %s [%s]", platforms_to_unload, entry.title, entry.unique_id)
                return False
    else:
        _logger.warning("config entry (%s) has no apis loaded?", entry.unique_id)

    url = entry.data.get(CONF_URL, None)
    if url is None:
        async_unsubscribe_topics(hass, entry_data["internal_mqtt"])
        service_status = hass.data[DOMAIN].get(SERVICE_STATUS_STORAGE_KEY, {})
        service_status.pop(entry.data["device"]["name"], None)

    hass.data[DOMAIN].pop(entry.entry_id, None)

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up hass_agent integration."""

    _logger.debug("integration setup start")

    def should_route_to_system_service(device_name: str, command: str | None, restart_cancel: bool) -> bool:
        command_name = "restart_cancel" if restart_cancel else command
        if command_name not in SYSTEM_SERVICE_COMMANDS:
            return False

        service_status = hass.data.get(DOMAIN, {}).get(SERVICE_STATUS_STORAGE_KEY, {}).get(device_name, {})
        if not isinstance(service_status, dict) or service_status.get("online") is not True:
            return False

        commands = service_status.get("commands")
        return any(
            isinstance(command, dict) and command.get("name") == command_name
            for command in commands
        ) if isinstance(commands, list) else False

    async def async_execute_command(call) -> None:
        device_name = call.data[CONF_DEVICE_NAME]
        command = call.data.get(CONF_COMMAND)
        restart_cancel = call.data[CONF_RESTART_CANCEL]

        if not restart_cancel and command is None:
            raise HomeAssistantError("command is required unless restart_cancel is true")

        payload = {CONF_RESTART_CANCEL: restart_cancel}
        if command is not None:
            payload[CONF_COMMAND] = command
        if not restart_cancel:
            payload[CONF_FORCE] = call.data[CONF_FORCE]
            payload[CONF_TIME] = call.data[CONF_TIME]
            comment = call.data.get(CONF_COMMENT)
            if comment is not None:
                payload[CONF_COMMENT] = comment

        topic = (
            f"hass.agent/system/{device_name}/cmd"
            if should_route_to_system_service(device_name, command, restart_cancel)
            else f"hass.agent/buttons/{device_name}/cmd"
        )

        await mqtt.async_publish(
            hass,
            topic,
            json.dumps(payload),
            qos=0,
            retain=False,
        )

    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SEND_NOTIFICATION,
        entity_domain=NOTIFY_DOMAIN,
        schema={
            vol.Required(ATTR_MESSAGE): cv.string,
            vol.Optional(ATTR_TITLE): cv.string,
            vol.Optional(ATTR_DATA, default={}): dict,
        },
        func="async_send_hass_agent_notification",
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE_COMMAND,
        async_execute_command,
        schema=vol.Schema(
            {
                vol.Required(CONF_DEVICE_NAME): cv.string,
                vol.Optional(CONF_COMMAND): vol.In(SYSTEM_COMMANDS),
                vol.Optional(CONF_COMMENT): cv.string,
                vol.Optional(CONF_FORCE, default=False): cv.boolean,
                vol.Optional(CONF_TIME, default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=315360000)),
                vol.Optional(CONF_RESTART_CANCEL, default=False): cv.boolean,
            }
        ),
    )

    return True
