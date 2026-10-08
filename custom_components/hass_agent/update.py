"""Update platform for HASS.Agent devices.

One update entity per PC, on both transports. It used to exist only on the HA
API transport, where there is no broker for Home Assistant's own MQTT discovery
to build it from; on MQTT the discovered entity did the job. A PC that switched
transports ended up with both, one of them always unavailable. The integration
now announces on MQTT (hass.agent/integration/{id}, retained) that it builds
the entity itself, and an agent 10.7.3 or newer clears its discovery config in
return. With an older agent the discovered entity is still there, and this
platform stays out of its way (see __init__).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATE_STATE
from .entity import HassAgentAvailableEntity, async_get_agent_device

UPDATE_STATE_STORAGE_KEY = "update_state"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the update entity from a config entry."""
    device = async_get_agent_device(hass, entry)

    if device is None:
        return False

    async_add_entities([HassAgentUpdate(entry.entry_id, entry.unique_id, device)])

    return True


class HassAgentUpdate(HassAgentAvailableEntity, UpdateEntity):
    """Shows an available HASS.Agent .NET10 release and installs it on request."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, entry_id: str, unique_id: str, device: dr.DeviceEntry) -> None:
        """Initialize the update entity."""
        self._entry_id = entry_id
        self._serial_number = unique_id
        self._attr_name = "Update"
        self._attr_unique_id = f"update_{unique_id}_app"
        self._attr_device_info = DeviceInfo(
            identifiers=device.identifiers,
            name=device.name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
        )
        self._setup_availability(entry_id)

    def _state(self) -> dict[str, Any]:
        state = self._entry_data().get(UPDATE_STATE_STORAGE_KEY)
        return state if isinstance(state, dict) else {}

    @property
    def installed_version(self) -> str | None:
        """Return the version running on the PC."""
        value = self._state().get("installed_version")
        return value if isinstance(value, str) and value else None

    @property
    def latest_version(self) -> str | None:
        """Return the newest release, or the installed one when up to date."""
        state = self._state()
        if state.get("update_available") is True:
            value = state.get("latest_version")
            if isinstance(value, str) and value:
                return value

        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return a link to the release notes."""
        value = self._state().get("release_url")
        # The PC sends it and the update dialog shows it as a link: GitHub pages only.
        return value if isinstance(value, str) and value.startswith("https://github.com/") else None

    async def async_added_to_hass(self) -> None:
        """Subscribe to state and availability updates."""
        await self._connect_availability()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE_STATE.format(self._entry_id),
                self._handle_update_state,
            )
        )

    @callback
    def _handle_update_state(self) -> None:
        self.async_write_ha_state()

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Ask the PC to install the update.

        The agent does the work itself: the tray app when it runs, the service
        otherwise (agent 10.7.3+). Over MQTT the request goes to the agent's
        install topic; the event covers the HA API transport.
        """
        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("ha_api_only", False):
            await mqtt.async_publish(
                self.hass,
                f"hass.agent/update/{self._serial_number}/install",
                "install",
                qos=0,
                retain=False,
            )

        self.hass.bus.async_fire(
            "hass_agent_command",
            {
                "serial_number": self._serial_number,
                "command_type": "update_install",
                "payload": {},
            },
        )
