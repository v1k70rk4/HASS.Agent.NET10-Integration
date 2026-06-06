"""Button platform for HASS.Agent system commands."""

from __future__ import annotations

import json

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN, SIGNAL_BUTTONS_UPDATED


SHUTDOWN_BUTTON_DELAY_SECONDS = 60
SYSTEM_SERVICE_COMMANDS = {"shutdown", "restart", "restart_cancel"}

BUTTON_DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="lock",
        translation_key="lock",
        icon="mdi:lock",
    ),
    ButtonEntityDescription(
        key="sleep",
        translation_key="sleep",
        icon="mdi:power-sleep",
    ),
    ButtonEntityDescription(
        key="monitor_off",
        translation_key="monitor_off",
        icon="mdi:monitor-off",
    ),
    ButtonEntityDescription(
        key="volume_up",
        translation_key="volume_up",
        icon="mdi:volume-plus",
    ),
    ButtonEntityDescription(
        key="volume_down",
        translation_key="volume_down",
        icon="mdi:volume-minus",
    ),
    ButtonEntityDescription(
        key="toggle_mute",
        translation_key="toggle_mute",
        icon="mdi:volume-mute",
    ),
    ButtonEntityDescription(
        key="shutdown",
        translation_key="shutdown",
        icon="mdi:power",
    ),
    ButtonEntityDescription(
        key="restart",
        translation_key="restart",
        icon="mdi:restart",
    ),
    ButtonEntityDescription(
        key="restart_cancel",
        translation_key="restart_cancel",
        icon="mdi:cancel",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up HASS.Agent command buttons from a config entry."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, entry.unique_id)})

    if device is None:
        return False

    translations = await async_get_translations(
        hass,
        hass.config.language,
        "entity",
        {DOMAIN},
    )
    command_signature = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("button_commands", ())
    command_set = set(command_signature) if isinstance(command_signature, (tuple, list)) else set()

    async_add_entities(
        [
            HassAgentCommandButton(entry.entry_id, entry.unique_id, device, description, translations)
            for description in BUTTON_DESCRIPTIONS
            if description.key in command_set
        ]
    )

    return True


class HassAgentCommandButton(ButtonEntity):
    """HASS.Agent command button."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry_id: str,
        unique_id: str,
        device: dr.DeviceEntry,
        description: ButtonEntityDescription,
        translations: dict[str, str],
    ) -> None:
        """Initialize the button."""
        self._entry_id = entry_id
        self.entity_description = description
        self._translations = translations
        self._command_topic = f"hass.agent/buttons/{device.name}/cmd"
        self._service_command_topic = f"hass.agent/system/{device.name}/cmd"
        self._attr_unique_id = f"button_{unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers=device.identifiers,
            name=device.name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
        )

    @property
    def available(self) -> bool:
        """Return if this command can currently be handled by app or service."""
        command = self.entity_description.key
        return self._can_use_service(command) or self._can_use_tray_app(command)

    async def async_added_to_hass(self) -> None:
        """Subscribe to command availability changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_BUTTONS_UPDATED.format(self._entry_id),
                self._handle_button_update,
            )
        )

    @callback
    def _handle_button_update(self) -> None:
        """Refresh the HA state when app or service command availability changes."""
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Send the command to the HASS.Agent Companion."""
        if not self.available:
            return

        payload = self._build_payload()
        topic = self._service_command_topic if self._can_use_service(self.entity_description.key) else self._command_topic

        await mqtt.async_publish(
            self.hass,
            topic,
            json.dumps(payload),
            qos=0,
            retain=False,
        )

    def _build_payload(self) -> dict[str, object]:
        command = self.entity_description.key

        if command == "restart_cancel":
            return {"restart_cancel": True}

        if command in {"shutdown", "restart"}:
            return {
                "command": command,
                "force": False,
                "time": SHUTDOWN_BUTTON_DELAY_SECONDS,
                "comment": self._shutdown_comment(command),
            }

        return {"command": command}

    def _shutdown_comment(self, command: str) -> str:
        translation_key = (
            "component.hass_agent.entity.button.shutdown_comment.name"
            if command == "shutdown"
            else "component.hass_agent.entity.button.restart_comment.name"
        )

        return self._translations.get(translation_key, "Stopped from Home Assistant")

    def _can_use_service(self, command: str) -> bool:
        if command not in SYSTEM_SERVICE_COMMANDS:
            return False

        service_status = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("service", {})
        if not isinstance(service_status, dict) or service_status.get("online") is not True:
            return False

        commands = service_status.get("commands")
        return isinstance(commands, list) and command in commands

    def _can_use_tray_app(self, command: str) -> bool:
        apis = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("apis", {})
        if not isinstance(apis, dict) or apis.get("buttons") is not True:
            return False

        commands = apis.get("commands")
        return isinstance(commands, list) and command in commands
