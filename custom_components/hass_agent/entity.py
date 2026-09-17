"""Shared entity helpers for HASS.Agent."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN


@callback
def async_get_agent_device(hass: HomeAssistant, entry: ConfigEntry) -> dr.DeviceEntry | None:
    """Return the device that belongs to this config entry.

    `DeviceRegistry.async_get_device` is deprecated (it stops working in Home Assistant
    2027.8): identifiers are no longer unique across config entries, so the lookup has to
    name the entry. The replacement arrived in 2026.8; older versions still get the old call.
    """
    registry = dr.async_get(hass)
    identifier = (DOMAIN, entry.unique_id)
    by_identifier = getattr(registry, "async_get_device_by_identifier", None)
    if by_identifier is not None:
        return by_identifier(identifier, entry.entry_id)

    return registry.async_get_device(identifiers={identifier})


def availability_signal(entry_id: str) -> str:
    """Dispatcher signal carrying the device online/offline state."""
    return f"hass_agent_availability_{entry_id}"


class HassAgentAvailableEntity:
    """Mixin tying an entity's availability to whoever provides it.

    A device has two independent providers: the tray app and the Windows service.
    Each announces itself separately (the app on its MQTT availability topic with a
    Last Will, the service on its own status topic), so closing the tray app must
    not take the service's sensors down with it.

    By default an entity follows the device — available while either side is up.
    Entities that know which side feeds them override `_provider_online` and grey
    out on their own when that side stops, while staying in Home Assistant.
    """

    _availability_entry_id: str

    def _setup_availability(self, entry_id: str) -> None:
        """Store the entry id; call from __init__ (hass is not available yet)."""
        self._availability_entry_id = entry_id

    async def _connect_availability(self) -> None:
        """Read the current state and subscribe; call from async_added_to_hass."""
        self._refresh_available()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                availability_signal(self._availability_entry_id),
                self._on_availability,
            )
        )

    def _entry_data(self) -> dict:
        """Return this device's shared state."""
        return self.hass.data.get(DOMAIN, {}).get(self._availability_entry_id, {}) or {}

    def _app_online(self, entry_data: dict) -> bool:
        """Whether the tray app is currently connected."""
        return bool(entry_data.get("app_online", True))

    def _service_online(self, entry_data: dict) -> bool:
        """Whether the Windows service is currently connected."""
        service = entry_data.get("service")
        return isinstance(service, dict) and service.get("online") is True

    def _provider_online(self, entry_data: dict) -> bool | None:
        """Whether this entity's provider is up, or None to follow the device."""
        return None

    @callback
    def _refresh_available(self) -> None:
        entry_data = self._entry_data()
        provider = self._provider_online(entry_data)
        self._attr_available = (
            bool(entry_data.get("available", True)) if provider is None else provider
        )

    @callback
    def _on_availability(self, online: bool) -> None:
        self._refresh_available()
        self.async_write_ha_state()
