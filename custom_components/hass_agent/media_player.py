from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from homeassistant.components import media_source, mqtt
from homeassistant.components.media_source import BrowseMediaSource, RootBrowseMediaSource
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.media_player.browse_media import (
    BrowseMedia,
    async_process_play_media_url,
)
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONF_ORIGINAL_DEVICE_NAME, CONF_HA_API

from homeassistant.components.mqtt.subscription import (
    async_prepare_subscribe_topics,
    async_subscribe_topics,
    async_unsubscribe_topics,
)
from homeassistant.config_entries import ConfigEntry

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)

from homeassistant.components.media_player.const import MediaPlayerState, MediaType
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

_logger = logging.getLogger(__name__)

MEDIA_PLAYER_AVAILABLE_TIMEOUT = 8

SUPPORT_HAMP = (
    MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.VOLUME_SET
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, entry.unique_id)})

    if device is None:
        return False

    original_device_name = entry.data.get(CONF_ORIGINAL_DEVICE_NAME, device.name)

    async_add_entities([HassAgentMediaPlayerDevice(entry.unique_id, entry.entry_id, device, original_device_name)])

    return True


class HassAgentMediaPlayerDevice(MediaPlayerEntity):
    """HASS.Agent MediaPlayer Device"""

    @callback
    def update_thumbnail(self, message: ReceiveMessage) -> None:
        """Update the cached media thumbnail."""
        if not message.payload:
            self.hass.data[DOMAIN][self._entry_id]["thumbnail"] = None
            self._attr_media_image_hash = None
            self.async_write_ha_state()
            return

        thumbnail = message.payload
        if isinstance(thumbnail, str):
            thumbnail = thumbnail.encode()

        thumbnail_hash = hashlib.sha256(thumbnail).hexdigest()
        if thumbnail_hash == self._attr_media_image_hash:
            return

        self.hass.data[DOMAIN][self._entry_id]["thumbnail"] = thumbnail
        self._attr_media_image_hash = thumbnail_hash
        self.async_write_ha_state()

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Return bytes for the Home Assistant media player image proxy."""
        thumbnail = self.hass.data[DOMAIN][self._entry_id].get("thumbnail")
        if thumbnail is None:
            return None, None

        return thumbnail, "image/png"

    @callback
    def updated(self, message: ReceiveMessage) -> None:
        """Updates the media player with new data from MQTT"""
        if not message.payload:
            _logger.debug("received empty update message on '%s', ignoring", message.topic)
            return

        try:
            payload = json.loads(message.payload)
        except ValueError:
            _logger.warning("received invalid media player JSON on '%s'", message.topic)
            return

        if not isinstance(payload, dict):
            _logger.warning("received non-object media player update on '%s'", message.topic)
            return

        state = payload.get("state")
        self._state = state.lower() if isinstance(state, str) else ""
        volume_level = payload.get("volume", 0)
        self._volume_level = volume_level if isinstance(volume_level, int | float) else 0
        self._muted = bool(payload.get("muted", False))
        self._available = True

        if self._state != "off":
            self._attr_media_album_artist = payload.get("albumartist")
            self._attr_media_album_name = payload.get("albumtitle")
            self._attr_media_artist = payload.get("artist")
            self._attr_media_title = payload.get("title")

            media_duration = payload.get("duration")
            media_position = payload.get("currentposition")
            self._attr_media_duration = media_duration if isinstance(media_duration, int | float) else None
            self._attr_media_position = media_position if isinstance(media_position, int | float) else None

            self._attr_media_position_updated_at = datetime.now(UTC)
        else:
            self._clear_media_state()

        self._last_updated = time.monotonic()
        self._schedule_availability_update()

        self.async_write_ha_state()

    @callback
    def _handle_ws_media_state(self, payload: Any) -> None:
        """Handle media state received via WebSocket failover transport."""
        if not isinstance(payload, dict):
            return

        state = payload.get("state")
        self._state = state.lower() if isinstance(state, str) else ""
        volume_level = payload.get("volume", 0)
        self._volume_level = volume_level if isinstance(volume_level, int | float) else 0
        self._muted = bool(payload.get("muted", False))
        self._available = True

        if self._state != "off":
            self._attr_media_album_artist = payload.get("albumartist")
            self._attr_media_album_name = payload.get("albumtitle")
            self._attr_media_artist = payload.get("artist")
            self._attr_media_title = payload.get("title")

            media_duration = payload.get("duration")
            media_position = payload.get("currentposition")
            self._attr_media_duration = media_duration if isinstance(media_duration, int | float) else None
            self._attr_media_position = media_position if isinstance(media_position, int | float) else None

            self._attr_media_position_updated_at = datetime.now(UTC)
        else:
            self._clear_media_state()

        self._last_updated = time.monotonic()
        self._schedule_availability_update()
        self.async_write_ha_state()

    @callback
    def _handle_ws_thumbnail(self, thumbnail_b64: Any) -> None:
        """Handle media thumbnail received via WebSocket failover transport."""
        import base64

        if not thumbnail_b64:
            self.hass.data[DOMAIN][self._entry_id]["thumbnail"] = None
            self._attr_media_image_hash = None
            self.async_write_ha_state()
            return

        try:
            thumbnail = base64.b64decode(thumbnail_b64) if isinstance(thumbnail_b64, str) else thumbnail_b64
        except Exception:
            return

        thumbnail_hash = hashlib.sha256(thumbnail).hexdigest()
        if thumbnail_hash == self._attr_media_image_hash:
            return

        self.hass.data[DOMAIN][self._entry_id]["thumbnail"] = thumbnail
        self._attr_media_image_hash = thumbnail_hash
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("ha_api_only", False):
            self._listeners = async_prepare_subscribe_topics(
                self.hass,
                self._listeners,
                {
                    f"{self._attr_unique_id}-state": {
                        "topic": f"hass.agent/media_player/{self._topic_id}/state",
                        "msg_callback": self.updated,
                        "qos": 0,
                    },
                    f"{self._attr_unique_id}-thumbnail": {
                        "topic": f"hass.agent/media_player/{self._topic_id}/thumbnail",
                        "msg_callback": self.update_thumbnail,
                        "qos": 0,
                        "encoding": None,
                    },
                },
            )

            await async_subscribe_topics(self.hass, self._listeners)

        # Also listen for media data coming via WebSocket transport.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"hass_agent_media_state_{self._entry_id}",
                self._handle_ws_media_state,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"hass_agent_media_thumbnail_{self._entry_id}",
                self._handle_ws_thumbnail,
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._listeners is not None:
            async_unsubscribe_topics(self.hass, self._listeners)

        if self._availability_unsub is not None:
            self._availability_unsub()
            self._availability_unsub = None

    def __init__(self, unique_id, entry_id, device: dr.DeviceEntry, original_device_name):
        """Initialize"""
        self._entry_id = entry_id
        self._serial_number = unique_id
        self._topic_id = unique_id
        self._name = device.name
        self._attr_device_info = DeviceInfo(
            identifiers=device.identifiers,
            name=device.name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
        )
        self._command_topic = f"hass.agent/media_player/{unique_id}/cmd"
        self._attr_unique_id = f"media_player_{unique_id}"
        self._attr_should_poll = False
        self._attr_media_image_hash = None
        self._available = False
        self._muted = False
        self._volume_level = 0
        self._playing = ""
        self._state = ""

        self._listeners = {}
        self._last_updated = 0
        self._availability_unsub: CALLBACK_TYPE | None = None
        self._original_device_name = original_device_name

    async def _send_command(self, command: str, data: Any = None) -> None:
        """Send a command"""
        _logger.debug("Sending command: %s", command)

        payload = {"command": command, "data": data}

        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("ha_api_only", False):
            await mqtt.async_publish(
                self.hass,
                self._command_topic,
                json.dumps(payload),
                qos=0,
                retain=False,
            )
        # Also fire on the event bus for WebSocket transport.
        self.hass.bus.async_fire("hass_agent_command", {
            "serial_number": self._serial_number,
            "command_type": "media_command",
            "payload": payload,
        })

    def _clear_media_state(self) -> None:
        """Clear stale metadata when playback stops."""
        self._attr_media_album_artist = None
        self._attr_media_album_name = None
        self._attr_media_artist = None
        self._attr_media_title = None
        self._attr_media_duration = None
        self._attr_media_position = None
        self._attr_media_position_updated_at = None

    def _schedule_availability_update(self) -> None:
        """Schedule a state update when the media player availability times out."""
        if self._availability_unsub is not None:
            self._availability_unsub()

        self._availability_unsub = async_call_later(
            self.hass,
            MEDIA_PLAYER_AVAILABLE_TIMEOUT + 1,
            self._handle_availability_update,
        )

    @callback
    def _handle_availability_update(self, _now: datetime) -> None:
        """Write state after the availability timeout window has passed."""
        self._availability_unsub = None
        self.async_write_ha_state()

    @property
    def name(self):
        """Return the name of the device"""
        return self._name

    @property
    def state(self):
        """Return the state of the device"""
        if self._state is None:
            return MediaPlayerState.OFF
        if self._state == "idle":
            return MediaPlayerState.IDLE
        if self._state == "playing":
            return MediaPlayerState.PLAYING
        if self._state == "paused":
            return MediaPlayerState.PAUSED

        return MediaPlayerState.IDLE

    @property
    def available(self):
        """Return if we're available"""

        diff = round(time.monotonic() - self._last_updated)
        return diff < MEDIA_PLAYER_AVAILABLE_TIMEOUT

    # @property
    # def media_title(self):
    #     """Return the title of current playing media"""
    #     return self._playing

    @property
    def volume_level(self):
        """Return the volume level of the media player (0..1)"""
        return self._volume_level / 100.0

    async def async_set_volume_level(self, volume: float) -> None:
        """Send new volume_level to device."""
        volume = round(volume * 100)
        await self._send_command("setvolume", volume)

    @property
    def is_volume_muted(self):
        """Return if volume is currently muted"""
        return self._muted

    @property
    def supported_features(self):
        """Flag media player features that are supported"""
        return SUPPORT_HAMP

    @property
    def device_class(self):
        """Announce ourselve as a speaker"""
        return MediaPlayerDeviceClass.SPEAKER

    @property
    def media_content_type(self):
        """Content type of current playing media"""
        return MediaType.MUSIC

    async def async_media_seek(self, position: float) -> None:
        self._attr_media_position = position
        self._attr_media_position_updated_at = datetime.now(UTC)
        await self._send_command("seek", position)

    async def async_volume_up(self):
        """Volume up the media player"""
        await self._send_command("volumeup")

    async def async_volume_down(self):
        """Volume down media player"""
        await self._send_command("volumedown")

    async def async_mute_volume(self, mute):
        """Mute the volume"""
        await self._send_command("mute", mute)

    async def async_media_play(self):
        """Send play command"""
        self._state = MediaPlayerState.PLAYING.value
        await self._send_command("play")

    async def async_media_pause(self):
        """Send pause command"""
        self._state = MediaPlayerState.PAUSED.value
        await self._send_command("pause")

    async def async_media_stop(self):
        """Send stop command"""
        self._state = MediaPlayerState.PAUSED.value
        await self._send_command("stop")

    async def async_media_next_track(self):
        """Send next track command"""
        await self._send_command("next")

    async def async_media_previous_track(self):
        """Send previous track command"""
        await self._send_command("previous")

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia | BrowseMediaSource | RootBrowseMediaSource:
        """Implement the websocket media browsing helper."""
        # If your media player has no own media sources to browse, route all browse commands
        # to the media source integration.
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            # This allows filtering content. In this case it will only show audio sources.
            content_filter=lambda item: item.media_content_type is not None
            and item.media_content_type.startswith("audio/"),
        )

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        enqueue: Any | None = None,
        announce: bool | None = None,
        **kwargs: Any,
    ) -> None:
        """Play media source"""
        if not media_type.startswith("music") and not media_type.startswith("audio/") and not media_type.startswith("provider"):
            _logger.error(
                "Invalid media type %r. Only %s is supported!",
                media_type,
                MediaType.MUSIC,
            )
            return

        if media_source.is_media_source_id(media_id):
            play_item = await media_source.async_resolve_media(self.hass, media_id, self.entity_id)

            # play_item returns a relative URL if it has to be resolved on the Home Assistant host
            # This call will turn it into a full URL
            media_id = async_process_play_media_url(self.hass, play_item.url)

        _logger.debug("Received media request from HA: %s", media_id)

        self._state = MediaPlayerState.PLAYING.value
        await self._send_command("playmedia", media_id)
