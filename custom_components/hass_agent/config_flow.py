"""Config flow for HASS.Agent"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import voluptuous as vol
from aiohttp import ClientError, ClientTimeout
from homeassistant import config_entries
from homeassistant.components.notify import ATTR_TITLE_DEFAULT
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SSL, CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .const import (
    CLIENT_RELEASES_URL,
    CONF_API_KEY,
    CONF_DEFAULT_NOTIFICATION_TITLE,
    CONF_DEVICE_NAME,
    CONF_HA_API,
    CONF_ORIGINAL_DEVICE_NAME,
    DOMAIN,
    MINIMUM_CLIENT_VERSION,
)

_logger = logging.getLogger(__name__)

_VERSION_PATTERN = re.compile(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?")


def _parse_version(value: object) -> tuple[int, int, int] | None:
    """Return (major, minor, patch) from a version string, ignoring any suffix."""
    if not isinstance(value, str):
        return None

    match = _VERSION_PATTERN.match(value)
    if match is None:
        return None

    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def _client_compatibility(device: dict[str, Any]) -> str | None:
    """Classify the Windows client that sent a discovery message.

    Returns "legacy" for the original pre-.NET10 HASS.Agent, "outdated" for a
    HASS.Agent .NET10 older than the supported minimum, and None when it is fine.

    The old client sends a discovery message of the same shape — this integration
    started out as a fork of the original one — so it used to pass validation and
    end up as a half-working device. Its version is what gives it away; a serial
    number does not, since the old client has one too. An unreadable version is
    let through, so an odd version string can never lock out a supported client.
    """
    version = _parse_version(device.get("sw_version"))
    minimum = _parse_version(MINIMUM_CLIENT_VERSION)
    if version is None or minimum is None:
        return None

    # The old client used 2.x, and before that calendar versions such as 2022.14.0 —
    # which would otherwise look newer than any .NET10 release.
    if version < (10, 0, 0) or version[0] >= 2000:
        return "legacy"

    if version < minimum:
        return "outdated"

    return None


@callback
def _async_report_client_version(
    hass: Any, serial_number: str, device_name: str, device: dict[str, Any]
) -> str | None:
    """Raise, or clear, the repair notice about this PC's Windows client."""
    issue_id = f"client_version_{serial_number}"
    status = _client_compatibility(device)

    if status is None:
        # Also clears a notice once the client has been updated.
        async_delete_issue(hass, DOMAIN, issue_id)
        return None

    async_create_issue(
        hass=hass,
        domain=DOMAIN,
        issue_id=issue_id,
        is_fixable=False,
        severity=IssueSeverity.ERROR if status == "legacy" else IssueSeverity.WARNING,
        learn_more_url=CLIENT_RELEASES_URL,
        translation_key=f"{status}_client",
        translation_placeholders={
            "name": device_name,
            "version": str(device.get("sw_version", "")),
            "minimum": MINIMUM_CLIENT_VERSION,
        },
    )
    return status


class OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            user_input[CONF_DEFAULT_NOTIFICATION_TITLE] = user_input[CONF_DEFAULT_NOTIFICATION_TITLE].strip()

            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DEFAULT_NOTIFICATION_TITLE,
                        default=self.config_entry.options.get(CONF_DEFAULT_NOTIFICATION_TITLE, ATTR_TITLE_DEFAULT),
                    ): str
                }
            ),
        )


class FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._device_name = ""
        self._data: dict[str, Any] = {}
        self._ha_api_unsub: Any = None
        self._ha_api_payload: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """Handle a flow initialized by MQTT discovery."""
        # Only the bare device topic (hass.agent/devices/<serial>) is a discovery
        # payload. Sub-topics like .../availability match the same wildcard but carry
        # plain text (online/offline), so ignore them quietly here.
        if "/" in discovery_info.topic.removeprefix("hass.agent/devices/"):
            return self.async_abort(reason="not_supported")

        if not discovery_info.payload:
            _logger.debug(
                "received empty discovery message on '%s', ignoring",
                discovery_info.topic,
            )
            return self.async_abort(reason="not_supported")

        try:
            payload = json.loads(discovery_info.payload)
            device = payload["device"]
            device_name = device["name"]
            serial_number = payload["serial_number"]
            apis = payload["apis"]
        except (ValueError, KeyError, TypeError):
            _logger.warning(
                "received invalid discovery payload on '%s'",
                discovery_info.topic,
            )
            return self.async_abort(reason="not_supported")

        if (
            not isinstance(device, dict)
            or not isinstance(device_name, str)
            or not isinstance(serial_number, str)
            or not isinstance(apis, dict)
        ):
            _logger.warning(
                "received malformed discovery payload on '%s'",
                discovery_info.topic,
            )
            return self.async_abort(reason="not_supported")

        _logger.debug("found device. Name: %s, Serial Number: %s", device_name, serial_number)

        # The old client is refused outright rather than added as a device that cannot
        # work; the repair notice is what tells the user, since discovery shows no UI.
        if _async_report_client_version(self.hass, serial_number, device_name, device) == "legacy":
            return self.async_abort(reason="legacy_client")

        self._data = {"device": device, "apis": apis}

        entry = await self.async_set_unique_id(serial_number)
        if not entry or (CONF_ORIGINAL_DEVICE_NAME not in entry.data):
            self._data[CONF_ORIGINAL_DEVICE_NAME] = device_name

        if entry:
            name_changed = device_name != entry.title
            old_title = entry.title
            switching_from_local_api = CONF_URL in entry.data
            switching_from_ha_api = entry.data.get(CONF_HA_API, False)
            entry_data = {**entry.data, **self._data}
            entry_data.pop(CONF_URL, None)
            entry_data.pop(CONF_HA_API, None)

            self.hass.config_entries.async_update_entry(
                entry,
                title=payload["device"]["name"],
                data=entry_data,
            )

            reload_required = name_changed or switching_from_local_api or switching_from_ha_api
            if reload_required:
                self.hass.config_entries.async_schedule_reload(entry.entry_id)

            if name_changed:
                # Delete any stale issue from a previous rename before creating the new one
                async_delete_issue(self.hass, DOMAIN, f"restart_required_{old_title}")

                async_create_issue(
                    hass=self.hass,
                    domain=DOMAIN,
                    issue_id=f"restart_required_{device_name}",
                    data={CONF_DEVICE_NAME: device_name},
                    is_fixable=True,
                    severity=IssueSeverity.WARNING,
                    translation_key="restart_required",
                    translation_placeholders={
                        "name": device_name,
                    },
                )

        self._abort_if_unique_id_configured()

        # "hass.agent/devices/#" is hardcoded in HASS.Agent's manifest
        assert discovery_info.subscribed_topic == "hass.agent/devices/#"

        self._device_name = device_name

        return await self.async_step_confirm()

    async def async_step_ha_api(self, discovery_info: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a flow initialized by HA API WebSocket auto-discovery."""
        if discovery_info is None:
            return self.async_abort(reason="not_supported")

        try:
            device = discovery_info["device"]
            device_name = device["name"]
            serial_number = discovery_info["serial_number"]
            apis = discovery_info["apis"]
        except (KeyError, TypeError):
            _logger.warning("received invalid HA API discovery payload")
            return self.async_abort(reason="not_supported")

        if (
            not isinstance(device, dict)
            or not isinstance(device_name, str)
            or not isinstance(serial_number, str)
            or not isinstance(apis, dict)
        ):
            _logger.warning("received malformed HA API discovery payload")
            return self.async_abort(reason="not_supported")

        _logger.debug("found device via HA API. Name: %s, Serial Number: %s", device_name, serial_number)

        if _async_report_client_version(self.hass, serial_number, device_name, device) == "legacy":
            return self.async_abort(reason="legacy_client")

        self._data = {"device": device, "apis": apis, CONF_HA_API: True}

        entry = await self.async_set_unique_id(serial_number)
        if not entry or (CONF_ORIGINAL_DEVICE_NAME not in entry.data):
            self._data[CONF_ORIGINAL_DEVICE_NAME] = device_name

        if entry:
            # Already configured — update with latest HA API data
            entry_data = {**entry.data, **self._data}
            self.hass.config_entries.async_update_entry(entry, data=entry_data)
            return self.async_abort(reason="already_configured")

        self._abort_if_unique_id_configured()

        self._device_name = device_name

        return await self.async_step_confirm()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle manual device addition."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["ha_api_info", "local_api"],
        )

    async def async_step_ha_api_info(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Adopt a device that talks to us over the HA API (WebSocket) transport.

        Automatic discovery only works once this integration is already set up,
        because the listener for it lives in async_setup — which Home Assistant
        does not run while there are no config entries. That leaves the very first
        device unable to arrive on its own, and MQTT is not an alternative for the
        people most likely to be here: HA API is the transport you pick when Home
        Assistant is not on the local network.

        So the flow itself listens while it is open. It is running, so it needs
        nothing set up beforehand.
        """
        errors: dict[str, str] = {}

        if self._ha_api_unsub is None:
            @callback
            def _capture(event) -> None:
                data = event.data
                if isinstance(data, dict) and isinstance(data.get("serial_number"), str):
                    self._ha_api_payload = data

            self._ha_api_unsub = self.hass.bus.async_listen("hass_agent_device_update", _capture)

        if user_input is not None:
            if self._ha_api_payload is None:
                errors["base"] = "no_discovery"
            else:
                payload = self._ha_api_payload
                self._async_stop_ha_api_listener()
                return await self.async_step_ha_api(payload)

        return self.async_show_form(
            step_id="ha_api_info",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    @callback
    def _async_stop_ha_api_listener(self) -> None:
        """Drop the discovery listener this flow set up, if any."""
        if self._ha_api_unsub is not None:
            self._ha_api_unsub()
            self._ha_api_unsub = None

    @callback
    def async_remove(self) -> None:
        """Clean up when the flow is abandoned."""
        self._async_stop_ha_api_listener()

    async def async_step_local_api(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            use_ssl = user_input[CONF_SSL]
            api_key = user_input.get(CONF_API_KEY, "").strip()

            protocol = "https" if use_ssl else "http"

            url = f"{protocol}://{host}:{port}"

            try:
                session = async_get_clientsession(self.hass)
                async with session.get(
                    f"{url}/info", timeout=ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()
                    response_json = await response.json()
            except (ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                try:
                    serial_number = response_json["serial_number"]
                    device_name = response_json["device"]["name"]
                except (KeyError, TypeError):
                    errors["base"] = "cannot_connect"
                else:
                    if not isinstance(serial_number, str) or not isinstance(device_name, str):
                        errors["base"] = "cannot_connect"
                    else:
                        entry = await self.async_set_unique_id(serial_number)
                        if not entry or (CONF_ORIGINAL_DEVICE_NAME not in entry.data):
                            self._data[CONF_ORIGINAL_DEVICE_NAME] = device_name

                        self._abort_if_unique_id_configured()

                        entry_data = {
                            CONF_URL: url,
                            CONF_ORIGINAL_DEVICE_NAME: device_name,
                        }
                        if api_key:
                            entry_data[CONF_API_KEY] = api_key

                        return self.async_create_entry(
                            title=device_name,
                            data=entry_data,
                            options={CONF_DEFAULT_NOTIFICATION_TITLE: ATTR_TITLE_DEFAULT},
                        )

        return self.async_show_form(
            step_id="local_api",
            data_schema=vol.Schema(
                # pylint: disable=no-value-for-parameter
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=5115): int,
                    vol.Required(CONF_SSL): bool,
                    vol.Optional(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm the setup."""

        if user_input is not None:
            return self.async_create_entry(
                title=self._device_name,
                data=self._data,
                options={CONF_DEFAULT_NOTIFICATION_TITLE: ATTR_TITLE_DEFAULT},
            )

        placeholders = {CONF_NAME: self._device_name}

        self.context["title_placeholders"] = placeholders

        self._set_confirm_only()

        return self.async_show_form(
            step_id="confirm",
            description_placeholders=placeholders,
        )
