"""Shared entity helpers for HASS.Agent."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN


def availability_signal(entry_id: str) -> str:
    """Dispatcher signal carrying the device online/offline state."""
    return f"hass_agent_availability_{entry_id}"


class HassAgentAvailableEntity:
    """Mixin tying an entity's availability to the device's online state.

    The device publishes online/offline on its MQTT availability topic (with a
    Last Will), so a clean shutdown — or a crash / network loss — turns the
    entities unavailable in Home Assistant instead of leaving stale values.
    """

    _availability_entry_id: str

    def _setup_availability(self, entry_id: str) -> None:
        """Store the entry id; call from __init__ (hass is not available yet)."""
        self._availability_entry_id = entry_id

    async def _connect_availability(self) -> None:
        """Read the current state and subscribe; call from async_added_to_hass."""
        data = self.hass.data.get(DOMAIN, {}).get(self._availability_entry_id, {})
        self._attr_available = bool(data.get("available", True))
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                availability_signal(self._availability_entry_id),
                self._on_availability,
            )
        )

    @callback
    def _on_availability(self, online: bool) -> None:
        self._attr_available = bool(online)
        self.async_write_ha_state()
