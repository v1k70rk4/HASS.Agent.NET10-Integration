"""Button platform for HASS.Agent system commands."""

from __future__ import annotations

import json
from dataclasses import replace

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_BUTTONS_UPDATED
from .entity import async_get_agent_device, availability_signal

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
    device = async_get_agent_device(hass, entry)

    if device is None:
        return False

    command_signature = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("button_commands", ())
    commands = _command_descriptors(command_signature)

    entities: list[ButtonEntity] = [
        HassAgentCommandButton(entry.entry_id, entry.unique_id, device, description, commands[description.key])
        for description in BUTTON_DESCRIPTIONS
        if description.key in commands
    ]

    custom_signature = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("custom_button_commands", ())
    for command in _custom_command_descriptors(custom_signature):
        entities.append(
            HassAgentCustomCommandButton(entry.entry_id, entry.unique_id, device, command[0], command[1])
        )

    async_add_entities(entities)

    return True


def _custom_command_descriptors(signature: object) -> list[tuple[str, str]]:
    """Return (id, name) tuples from a stored custom command signature."""
    descriptors: list[tuple[str, str]] = []
    if not isinstance(signature, (tuple, list)):
        return descriptors

    for item in signature:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        command_id = item[0]
        name = item[1]
        if isinstance(command_id, str) and command_id and isinstance(name, str) and name:
            descriptors.append((command_id, name))

    return descriptors


def _custom_command_ids(commands: object) -> set[str]:
    """Return the set of custom command ids in a raw discovery payload."""
    ids: set[str] = set()
    if not isinstance(commands, list):
        return ids

    for item in commands:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            ids.add(item["id"])

    return ids


def _command_descriptors(command_signature: object) -> dict[str, tuple[str, str | None]]:
    """Return configured command display names keyed by command id."""
    commands: dict[str, tuple[str, str | None]] = {}
    if not isinstance(command_signature, (tuple, list)):
        return commands

    for item in command_signature:
        if not isinstance(item, (tuple, list)) or len(item) not in {2, 3}:
            continue

        command = item[0]
        display_name = item[1]
        comment = item[2] if len(item) == 3 else None
        if isinstance(command, str) and command and isinstance(display_name, str) and display_name:
            commands[command] = (
                display_name,
                comment if isinstance(comment, str) and comment else None,
            )

    return commands


def _command_list_contains(commands: object, command: str) -> bool:
    """Return whether a raw command payload contains a command id."""
    if not isinstance(commands, list):
        return False

    for item in commands:
        if isinstance(item, dict) and item.get("name") == command:
            return True

    return False


class HassAgentCommandButton(ButtonEntity):
    """HASS.Agent command button."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry_id: str,
        unique_id: str,
        device: dr.DeviceEntry,
        description: ButtonEntityDescription,
        command_info: tuple[str, str | None],
    ) -> None:
        """Initialize the button."""
        self._entry_id = entry_id
        self._serial_number = unique_id
        self.entity_description = replace(description, translation_key=None)
        display_name, comment = command_info
        self._attr_name = display_name
        self._comment = comment
        self._command_topic = f"hass.agent/buttons/{unique_id}/cmd"
        self._service_command_topic = f"hass.agent/system/{unique_id}/cmd"
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
        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("available", True):
            return False
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
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                availability_signal(self._entry_id),
                self._on_device_availability,
            )
        )

    @callback
    def _on_device_availability(self, online: bool) -> None:
        """Re-evaluate availability when the device goes online/offline."""
        self.async_write_ha_state()

    @callback
    def _handle_button_update(self) -> None:
        """Refresh the HA state when app or service command availability changes."""
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Send the command to the HASS.Agent Companion."""
        if not self.available:
            return

        payload = self._build_payload()

        use_service = self._can_use_service(self.entity_description.key)

        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("ha_api_only", False):
            topic = self._service_command_topic if use_service else self._command_topic

            await mqtt.async_publish(
                self.hass,
                topic,
                json.dumps(payload),
                qos=0,
                retain=False,
            )
        # Also fire on the event bus for WebSocket transport. MQTT picks a side by topic;
        # over the WebSocket both the app and the service see the same event, so name the
        # one that should act on it.
        self.hass.bus.async_fire("hass_agent_command", {
            "serial_number": self._serial_number,
            "command_type": "button_command",
            "target": "service" if use_service else "app",
            "payload": payload,
        })

    def _build_payload(self) -> dict[str, object]:
        command = self.entity_description.key

        if command == "restart_cancel":
            return {"restart_cancel": True}

        if command in {"shutdown", "restart"}:
            return {
                "command": command,
                "force": False,
                "time": SHUTDOWN_BUTTON_DELAY_SECONDS,
                "comment": self._comment or "Stopped from Home Assistant",
            }

        return {"command": command}

    def _can_use_service(self, command: str) -> bool:
        if command not in SYSTEM_SERVICE_COMMANDS:
            return False

        service_status = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("service", {})
        if not isinstance(service_status, dict) or service_status.get("online") is not True:
            return False

        commands = service_status.get("commands")
        return _command_list_contains(commands, command)

    def _can_use_tray_app(self, command: str) -> bool:
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        # The tray app's discovery is retained, so it still lists commands after the
        # app closes — only the live connection tells us it can actually run them.
        if not entry_data.get("app_online", True):
            return False

        apis = entry_data.get("apis", {})
        if not isinstance(apis, dict) or apis.get("buttons") is not True:
            return False

        commands = apis.get("commands")
        return _command_list_contains(commands, command)


class HassAgentCustomCommandButton(ButtonEntity):
    """A user-defined custom command exposed as a button.

    HASS.Agent only advertises the id and name; pressing the button asks the
    Companion to run the command the user defined for that id — Home Assistant
    never sends the underlying program or script.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:console"

    def __init__(
        self,
        entry_id: str,
        unique_id: str,
        device: dr.DeviceEntry,
        command_id: str,
        name: str,
    ) -> None:
        """Initialize the custom command button."""
        self._entry_id = entry_id
        self._serial_number = unique_id
        self._command_id = command_id
        self._attr_name = name
        self._command_topic = f"hass.agent/buttons/{unique_id}/cmd"
        self._service_command_topic = f"hass.agent/system/{unique_id}/cmd"
        self._attr_unique_id = f"button_{unique_id}_customcmd_{command_id}"
        self._attr_device_info = DeviceInfo(
            identifiers=device.identifiers,
            name=device.name,
            manufacturer=device.manufacturer,
            model=device.model,
            sw_version=device.sw_version,
        )

    @property
    def available(self) -> bool:
        """Return whether app or service can currently run this command."""
        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("available", True):
            return False
        return self._can_use_service() or self._can_use_tray_app()

    async def async_added_to_hass(self) -> None:
        """Subscribe to availability changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_BUTTONS_UPDATED.format(self._entry_id),
                self._handle_button_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                availability_signal(self._entry_id),
                self._on_device_availability,
            )
        )

    @callback
    def _on_device_availability(self, online: bool) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_button_update(self) -> None:
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Ask the Companion to run the custom command."""
        if not self.available:
            return

        payload = {"command": self._command_id}

        use_service = self._can_use_service()

        if not self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("ha_api_only", False):
            topic = self._service_command_topic if use_service else self._command_topic
            await mqtt.async_publish(
                self.hass,
                topic,
                json.dumps(payload),
                qos=0,
                retain=False,
            )

        # See the note on the built-in button: the WebSocket needs the target named.
        self.hass.bus.async_fire("hass_agent_command", {
            "serial_number": self._serial_number,
            "command_type": "button_command",
            "target": "service" if use_service else "app",
            "payload": payload,
        })

    def _can_use_service(self) -> bool:
        service_status = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("service", {})
        if not isinstance(service_status, dict) or service_status.get("online") is not True:
            return False
        return self._command_id in _custom_command_ids(service_status.get("custom_commands"))

    def _can_use_tray_app(self) -> bool:
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        if not entry_data.get("app_online", True):
            return False

        apis = entry_data.get("apis", {})
        if not isinstance(apis, dict) or apis.get("buttons") is not True:
            return False
        return self._command_id in _custom_command_ids(apis.get("custom_commands"))
