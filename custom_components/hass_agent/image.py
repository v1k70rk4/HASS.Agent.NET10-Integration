"""Image platform for HASS.Agent: the last screenshot the PC sent.

The PC takes a screenshot when it is asked to, with the Screenshot button (client
10.13.1+, tray app, off until it is ticked on the PC itself), and never by itself. The
picture comes over MQTT as it is, or over the HA API through `hass_agent/screenshot`; it
is kept in memory only, so it is gone after a restart of Home Assistant until the next
one is asked for.
"""

from __future__ import annotations

import logging
import zlib
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.mqtt.subscription import (
    async_prepare_subscribe_topics,
    async_subscribe_topics,
    async_unsubscribe_topics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MAX_SCREENSHOT_BYTES, SIGNAL_SCREENSHOT
from .entity import HassAgentAvailableEntity, async_get_agent_device

_LOGGER = logging.getLogger(__name__)


_JPEG_START = b"\xff\xd8"
_JPEG_END = b"\xff\xd9"
_PNG_START = b"\x89PNG\r\n\x1a\n"


def _is_whole_jpeg(image: bytes) -> bool:
    """Whether the bytes are laid out as a JPEG picture from its first marker to its last.

    After the start marker come segments, each with its marker and its length; one of
    them is the frame header, which says how wide and high the picture is; then the scan
    starts, and the picture's data runs up to the end marker, which must be the last two
    bytes. The data itself is not decoded.
    """
    size = len(image)
    if not image.startswith(_JPEG_START) or not image.endswith(_JPEG_END):
        return False

    position = len(_JPEG_START)
    has_frame = False
    while position < size:
        if image[position] != 0xFF:
            return False
        # A marker may have fill bytes before it.
        while position < size and image[position] == 0xFF:
            position += 1
        if position >= size:
            return False
        marker = image[position]
        position += 1
        # No segment these: a stuffed byte, the markers of a scan's own data, a second
        # start, and the end before any scan.
        if marker in (0x00, 0x01) or 0xD0 <= marker <= 0xD9:
            return False
        if position + 2 > size:
            return False
        length = int.from_bytes(image[position : position + 2], "big")
        if length < 2 or position + length > size - len(_JPEG_END):
            return False
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            # The frame header: precision, height, width, how many components.
            if length < 8:
                return False
            height = int.from_bytes(image[position + 3 : position + 5], "big")
            width = int.from_bytes(image[position + 5 : position + 7], "big")
            if width == 0 or height == 0:
                return False
            has_frame = True
        if marker == 0xDA:
            # The scan: there must be a frame it belongs to, and data after its header.
            return has_frame and position + length < size - len(_JPEG_END)
        position += length
    return False


def _is_whole_png(image: bytes) -> bool:
    """Whether the bytes are laid out as a PNG picture from its signature to its last chunk.

    After the signature come chunks, each with its length, its type, its data and a
    checksum of the two before: the header first, saying how wide and high the picture
    is, the picture's data among them, the end chunk last and at the end of the bytes.
    Every checksum is worked out; the data itself is not unpacked.
    """
    size = len(image)
    if not image.startswith(_PNG_START):
        return False

    position = len(_PNG_START)
    first = True
    has_data = False
    while position + 12 <= size:
        length = int.from_bytes(image[position : position + 4], "big")
        kind = image[position + 4 : position + 8]
        end = position + 12 + length
        if end > size:
            return False
        if zlib.crc32(image[position + 4 : end - 4]) != int.from_bytes(image[end - 4 : end], "big"):
            return False
        if first:
            if kind != b"IHDR" or length != 13:
                return False
            width = int.from_bytes(image[position + 8 : position + 12], "big")
            height = int.from_bytes(image[position + 12 : position + 16], "big")
            if width == 0 or height == 0:
                return False
            first = False
        elif kind == b"IDAT":
            has_data = True
        elif kind == b"IEND":
            return has_data and length == 0 and end == size
        position = end
    return False


def screenshot_content_type(image: Any) -> str | None:
    """The type of a picture the PC sent, or None when it is not one that is taken.

    Told from the bytes, not from what the sender says: JPEG is what the client sends, PNG
    is taken as well. The picture must be whole and laid out as its kind is, from its
    first byte to its last: one that was cut off or mixed up on the way would otherwise
    take the place of the last good one. Its layout is read, its data is not decoded:
    Home Assistant hands the bytes on as they are, and a decoder would be one more thing
    for the integration to bring along.
    """
    if not isinstance(image, bytes) or not image or len(image) > MAX_SCREENSHOT_BYTES:
        return None
    if _is_whole_jpeg(image):
        return "image/jpeg"
    if _is_whole_png(image):
        return "image/png"
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the screenshot image of a PC that offers the screenshot command."""
    device = async_get_agent_device(hass, entry)
    if device is None:
        return False

    async_add_entities([HassAgentScreenshotImage(hass, entry.entry_id, entry.unique_id, device)])
    return True


class HassAgentScreenshotImage(HassAgentAvailableEntity, ImageEntity):
    """The last screenshot of the PC."""

    _attr_has_entity_name = True
    _attr_translation_key = "screenshot"
    _attr_icon = "mdi:monitor-screenshot"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry_id: str, unique_id: str, device: dr.DeviceEntry) -> None:
        """Initialize the image."""
        ImageEntity.__init__(self, hass)
        self._entry_id = entry_id
        self._serial_number = unique_id
        self._attr_unique_id = f"image_{unique_id}_screenshot"
        self._attr_device_info = DeviceInfo(
            identifiers=device.identifiers,
            name=device.name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
        )
        self._image: bytes | None = None
        self._listeners: dict[str, Any] = {}
        self._setup_availability(entry_id)

    def _provider_online(self, entry_data: dict) -> bool | None:
        """The tray app takes the screenshot; the service has no desktop."""
        return self._app_online(entry_data)

    async def async_image(self) -> bytes | None:
        """Return the last screenshot."""
        return self._image

    @callback
    def _set_image(self, image: Any, source: str) -> None:
        content_type = screenshot_content_type(image)
        if content_type is None:
            _LOGGER.warning(
                "A screenshot of %s over %s was not taken: it is not a whole JPEG or PNG picture of at most %s KB",
                self._serial_number,
                source,
                MAX_SCREENSHOT_BYTES // 1024,
            )
            return

        self._image = image
        self._attr_content_type = content_type
        self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()

    @callback
    def _mqtt_image(self, message: ReceiveMessage) -> None:
        """A screenshot over MQTT: the picture itself is the payload."""
        if not message.payload:
            return
        self._set_image(message.payload, "MQTT")

    @callback
    def _ws_image(self, image: bytes) -> None:
        """A screenshot over the HA API, already decoded."""
        self._set_image(image, "the HA API")

    async def async_added_to_hass(self) -> None:
        """Listen on both transports."""
        await super().async_added_to_hass()
        await self._connect_availability()

        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("ha_api_only", False):
            self._listeners = async_prepare_subscribe_topics(
                self.hass,
                self._listeners,
                {
                    f"{self._attr_unique_id}-image": {
                        "topic": f"hass.agent/screenshot/{self._serial_number}/image",
                        "msg_callback": self._mqtt_image,
                        "qos": 0,
                        "encoding": None,
                    },
                },
            )
            await async_subscribe_topics(self.hass, self._listeners)

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_SCREENSHOT.format(self._entry_id), self._ws_image)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from the screenshot topic."""
        if self._listeners:
            self._listeners = async_unsubscribe_topics(self.hass, self._listeners)
