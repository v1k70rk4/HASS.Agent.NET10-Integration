"""WebSocket commands of the HA API transport, for a PC with a token of its own user.

Before these, the client used Home Assistant's own `fire_event` and `subscribe_events`,
which take an administrator's token: a PC that was broken into gave away a token that
can change everything in Home Assistant. With these two commands the PC can use a user
of its own who is not an administrator. What such a user may do through them is narrow:

- `hass_agent/fire` puts one of the client's own event types on the bus, for the PC's
  own serial number only. The listeners that handle them are the ones `fire_event`
  always fed, so nothing else changes.
- `hass_agent/subscribe` passes on the commands for that one PC, and nothing else
  (`subscribe_events` showed every PC's commands to every PC).

A user who is not an administrator speaks for a PC once an administrator has approved
it: a new PC through the usual discovery confirmation, a PC already set up through a
confirmation of its own. Administrators are let through, as `fire_event` lets them.

- `hass_agent/provision`, for an administrator only, is the easy way there: a PC that
  connects with an administrator's token asks for a user of its own, and gets one with
  a token, already approved for it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
from homeassistant.components import websocket_api
from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .config_flow import valid_serial
from .const import CONF_USER_ID, DISCOVERY_USER_ID, DOMAIN, SIGNAL_PENDING_DEVICE

# The events the client sends, the ones the integration listens to.
CLIENT_EVENTS = frozenset(
    {
        "hass_agent_device_update",
        "hass_agent_service_update",
        "hass_agent_update_state",
        "hass_agent_sensor_update",
        "hass_agent_media_update",
        "hass_agent_media_thumbnail",
        "hass_agent_notification_action",
        "hass_agent_hotkey",
        "hass_agent_persistent_notification",
        "hass_agent_availability",
    }
)

# The one command a client sends itself: the tray app asks its own service to install
# an update when there is no broker to carry the request.
CLIENT_COMMANDS = frozenset({"install_update"})

COMMAND_EVENT = "hass_agent_command"

# As long as the profile page of Home Assistant offers for a long-lived token.
PROVISIONED_TOKEN_LIFETIME = timedelta(days=3650)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the commands."""
    websocket_api.async_register_command(hass, ws_fire)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_provision)


@callback
def _entry_for(hass: HomeAssistant, serial_number: str) -> ConfigEntry | None:
    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, serial_number)
    return None if entry is None or entry.source == SOURCE_IGNORE else entry


@callback
def may_speak_for(hass: HomeAssistant, user: Any, serial_number: str) -> bool:
    """Whether this user may send and receive for this PC."""
    if user is None:
        return False
    if user.is_admin:
        return True
    entry = _entry_for(hass, serial_number)
    return entry is not None and entry.data.get(CONF_USER_ID) == user.id


@callback
def _ask_for_approval(hass: HomeAssistant, data: dict[str, Any], user_id: str) -> None:
    """A PC announced itself with a user not approved for it: ask an administrator.

    For a new PC this is the usual discovery; for one already set up, a confirmation
    of its own. Home Assistant keeps one flow per PC, so repeated announcements do not
    pile up.
    """
    pending = {**data, DISCOVERY_USER_ID: user_id}
    # The manual "HA API" step, if one is open, takes it from here as well.
    async_dispatcher_send(hass, SIGNAL_PENDING_DEVICE, pending)
    hass.async_create_task(
        hass.config_entries.flow.async_init(DOMAIN, context={"source": "ha_api"}, data=pending)
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "hass_agent/fire",
        vol.Required("event_type"): vol.In(CLIENT_EVENTS | {COMMAND_EVENT}),
        vol.Required("event_data"): dict,
    }
)
@callback
def ws_fire(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Put one of the client's events on the bus, for the PC's own serial number."""
    event_type = msg["event_type"]
    data = msg["event_data"]
    serial_number = data.get("serial_number")
    if not valid_serial(serial_number):
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "serial_number is missing or not usable")
        return

    if event_type == COMMAND_EVENT and data.get("command_type") not in CLIENT_COMMANDS:
        connection.send_error(msg["id"], websocket_api.ERR_UNAUTHORIZED, "the client sends no such command")
        return

    if not may_speak_for(hass, connection.user, serial_number):
        if event_type == "hass_agent_device_update":
            _ask_for_approval(hass, data, connection.user.id)
        connection.send_error(
            msg["id"],
            websocket_api.ERR_UNAUTHORIZED,
            "this PC is not approved for this Home Assistant user yet; an administrator "
            "can confirm it under Settings > Devices & services",
        )
        return

    hass.bus.async_fire(event_type, data, context=connection.context(msg))
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "hass_agent/subscribe",
        vol.Required("serial_number"): str,
    }
)
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Pass on the commands for one PC.

    The subscription itself is allowed for any usable serial number, so a PC waiting for
    approval need not reconnect once it is approved: each command is checked as it goes.
    """
    serial_number = msg["serial_number"]
    if not valid_serial(serial_number):
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "serial_number is not usable")
        return

    @callback
    def forward(event: Event) -> None:
        if event.data.get("serial_number") != serial_number:
            return
        if not may_speak_for(hass, connection.user, serial_number):
            return
        connection.send_message(websocket_api.event_message(msg["id"], event.as_dict()))

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(COMMAND_EVENT, forward)
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "hass_agent/provision",
        vol.Required("serial_number"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_provision(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Give a PC a Home Assistant user of its own, not an administrator, and a token for it.

    Asked by the PC itself while it is connected with an administrator's token, after
    its user said yes. The user has no password, so nobody can log in with it; it is
    approved for the PC at once. A PC that has such a user already gets a new token for
    the same one.
    """
    serial_number = msg["serial_number"]
    entry = _entry_for(hass, serial_number) if valid_serial(serial_number) else None
    if entry is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "no HASS.Agent device with this serial number")
        return

    user = None
    if (user_id := entry.data.get(CONF_USER_ID)) is not None:
        user = await hass.auth.async_get_user(user_id)
        if user is not None and (user.is_admin or not user.is_active or user.system_generated):
            user = None
    if user is None:
        user = await hass.auth.async_create_user(f"HASS.Agent {entry.title}", group_ids=[GROUP_ID_USER])

    # The PC's earlier token goes: the PC switches to the new one, and Home Assistant
    # wants the name of a long-lived token to be unique for its user anyway.
    client_name = f"HASS.Agent {entry.title}"
    for old in list(user.refresh_tokens.values()):
        if old.token_type == TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN and old.client_name == client_name:
            hass.auth.async_remove_refresh_token(old)

    refresh_token = await hass.auth.async_create_refresh_token(
        user,
        client_name=client_name,
        token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
        access_token_expiration=PROVISIONED_TOKEN_LIFETIME,
    )
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_USER_ID: user.id})
    connection.send_result(
        msg["id"],
        {"access_token": hass.auth.async_create_access_token(refresh_token), "user": user.name},
    )
