"""Notify platform for HASS.Agent."""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.components import mqtt
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_NOTIFICATION_TITLE,
    CONF_HA_API,
    CONF_ORIGINAL_DEVICE_NAME,
    DOMAIN,
)

_logger = logging.getLogger(__name__)

# How long the client has to fetch a picture that lives on this Home Assistant. It does so
# the moment the notification arrives and keeps its own copy.
IMAGE_LINK_LIFETIME = timedelta(minutes=5)

# A camera or image entity given as the picture: its current frame is what is sent.
_IMAGE_ENTITY = re.compile(r"^(camera|image)\.[a-z0-9_]+$")


def _prepare_image(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Make a picture that lives on this Home Assistant fetchable by the client.

    `image` may be a camera or image entity, or a path on this Home Assistant
    (`/local/...`, `/api/camera_proxy/...`). Such a path needs a login the client does not
    have, so it is signed for a few minutes. The client gets it twice: as `image_path`,
    which it joins to the Home Assistant address it is itself connected to (HA API
    transport), and as a full address in `image`, built from this instance's own URL, for a
    client that only knows the broker. A full web address is passed on untouched.
    """
    image = data.get("image")
    if not isinstance(image, str):
        return data

    image = image.strip()
    if match := _IMAGE_ENTITY.match(image):
        image = f"/api/{match.group(1)}_proxy/{image}"

    if not image.startswith("/"):
        return data

    signed = async_sign_path(hass, image, IMAGE_LINK_LIFETIME, use_content_user=True)
    prepared = dict(data)
    prepared["image_path"] = signed
    try:
        prepared["image"] = f"{get_url(hass)}{signed}"
    except NoURLAvailableError:
        # No address of its own to offer; a client on the HA API transport has one.
        prepared.pop("image")
    return prepared


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

        data = _prepare_image(self.hass, data or {})
        payload = {"message": message, "title": title, "data": data}

        _logger.debug("Sending notification")

        url = self._entry.data.get(CONF_URL, None)
        is_ha_api_only = self._entry.data.get(CONF_HA_API, False)

        if url is None:
            if not is_ha_api_only:
                await mqtt.async_publish(
                    self.hass,
                    f"hass.agent/notifications/{self._entry.unique_id}",
                    json.dumps(payload),
                    qos=0,
                    retain=False,
                )
            # Also fire on the event bus for WebSocket transport.
            self.hass.bus.async_fire("hass_agent_command", {
                "serial_number": self._entry.unique_id,
                "command_type": "notification",
                "payload": payload,
            })
        else:
            session = async_get_clientsession(self.hass)
            headers = {}
            api_key = self._entry.data.get(CONF_API_KEY)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            try:
                async with session.post(
                    f"{url}/notify",
                    json=payload,
                    headers=headers,
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
