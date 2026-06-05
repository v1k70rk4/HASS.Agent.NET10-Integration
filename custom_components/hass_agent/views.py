from typing import Any
from homeassistant.components.http.view import HomeAssistantView
from aiohttp import web

from homeassistant.core import HomeAssistant

from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


class MediaPlayerThumbnailView(HomeAssistantView):
    url = "/api/hass_agent/{media_player:.*}/thumbnail.png"

    name = "api:hass_agent:media_player_thumbnails"

    # NOTE: Authentication disabled to allow media player thumbnails to load
    # in contexts where auth headers aren't sent (e.g., <img> tags).
    # Consider enabling auth if security is a concern.
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(
        self,
        request: web.Request,
        **kwargs: Any,
    ) -> web.Response:

        media_player = kwargs["media_player"]

        entity_registry = er.async_get(self.hass)

        entity = entity_registry.async_get(media_player)

        if entity is None:
            return web.Response(status=404)

        entry_data = self.hass.data.get(DOMAIN, {}).get(entity.config_entry_id)
        if entry_data is None:
            return web.Response(status=404)

        thumbnail = entry_data.get("thumbnail")

        if thumbnail is None:
            return web.Response(status=404)

        return web.Response(
            body=thumbnail,
            content_type="image/png",
            status=200,
            headers={"Content-Length": f"{len(thumbnail)}"},
        )
