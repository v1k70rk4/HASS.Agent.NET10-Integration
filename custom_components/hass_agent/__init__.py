"""The HASS.Agent integration."""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import ClientError, ClientTimeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.mqtt.subscription import (
    async_prepare_subscribe_topics,
    async_subscribe_topics,
    async_unsubscribe_topics,
)
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.NOTIFY, Platform.EVENT]

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
        else:
            _logger.warning("failed to unload %s for device: %s [%s]", platform, device_name, entry.unique_id)


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HASS.Agent from a config entry."""

    _logger.debug("setting up device from config entry: %s [%s]", entry.title, entry.unique_id)

    hass.data.setdefault(DOMAIN, {})

    hass.data[DOMAIN].setdefault(
        entry.entry_id,
        {
            "internal_mqtt": {},
            "apis": {},
            "thumbnail": None,
            "loaded": {"media_player": False, "notifications": False, "event": False},
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

            if cached != apis:
                hass.async_create_background_task(handle_apis_changed(hass, entry, apis), "hass.agent-mqtt")
                hass.data[DOMAIN][entry.entry_id]["apis"] = apis

        sub_state = async_prepare_subscribe_topics(
            hass,
            sub_state,
            {
                f"{entry.unique_id}-apis": {
                    "topic": f"hass.agent/devices/{device_name}",
                    "msg_callback": updated,
                    "qos": 0,
                }
            },
        )

        await async_subscribe_topics(hass, sub_state)

        hass.data[DOMAIN][entry.entry_id]["internal_mqtt"] = sub_state

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

    hass.data[DOMAIN].pop(entry.entry_id, None)

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up hass_agent integration."""

    _logger.debug("integration setup start")

    return True
