"""Notify platform for HASS.Agent."""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.components import mqtt
from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_DEFAULT_NOTIFICATION_TITLE,
    CONF_ORIGINAL_DEVICE_NAME,
)

_logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HASS.Agent notify entities from a config entry."""

    device_name = entry.data.get("device", {}).get("name", entry.title)
    original_device_name = entry.data.get(CONF_ORIGINAL_DEVICE_NAME, device_name)

    async_add_entities(
        [HassAgentNotifyEntity(hass, entry, device_name, original_device_name)]
    )


class HassAgentNotifyEntity(NotifyEntity):
    """HASS.Agent notification entity."""

    _attr_has_entity_name = True
    _attr_name = "Notifications"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_name: str,
        original_device_name: str,
    ) -> None:
        """Initialize the notification entity."""
        self._entry = entry
        self._device_name = device_name
        self._original_device_name = original_device_name
        self._attr_unique_id = f"notify_{entry.unique_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
        )

    async def async_send_message(
        self,
        message: str,
        title: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Send a notification message."""
        if title is None:
            title = self._entry.options.get(
                CONF_DEFAULT_NOTIFICATION_TITLE, "Home Assistant"
            )

        data = kwargs.get("data") or {}
        await self.async_send_hass_agent_notification(message, title, data)

    async def async_send_hass_agent_notification(
        self,
        message: str,
        title: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Send a HASS.Agent notification with integration-specific data."""
        _logger.debug("Preparing HASS.Agent notification for %s", self._device_name)

        if title is None:
            title = self._entry.options.get(
                CONF_DEFAULT_NOTIFICATION_TITLE, "Home Assistant"
            )

        data = data or {}
        payload = {"message": message, "title": title, "data": data}

        _logger.debug("Sending notification")

        url = self._entry.data.get(CONF_URL, None)

        if url is None:
            await mqtt.async_publish(
                self.hass,
                f"hass.agent/notifications/{self._device_name}",
                json.dumps(payload),
                qos=0,
                retain=False,
            )
        else:
            session = async_get_clientsession(self.hass)
            try:
                async with session.post(
                    f"{url}/notify",
                    json=payload,
                    timeout=ClientTimeout(total=10),
                ) as response:
                    if response.ok:
                        _logger.debug(
                            "Notification sent successfully (status %d)",
                            response.status,
                        )
                    else:
                        _logger.error(
                            "Failed to send notification: HTTP %d %s",
                            response.status,
                            response.reason,
                        )
            except (ClientError, TimeoutError) as ex:
                _logger.error("Error sending notification to %s: %s", url, ex)
