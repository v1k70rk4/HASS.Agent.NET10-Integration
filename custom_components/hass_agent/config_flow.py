"""Config flow for HASS.Agent"""

from __future__ import annotations
import json
import logging
import voluptuous as vol

from typing import Any

from aiohttp import ClientError, ClientTimeout

from homeassistant.components.notify import ATTR_TITLE_DEFAULT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SSL, CONF_URL
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue

from .const import DOMAIN, CONF_DEFAULT_NOTIFICATION_TITLE, CONF_ORIGINAL_DEVICE_NAME, CONF_DEVICE_NAME

_logger = logging.getLogger(__name__)


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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """Handle a flow initialized by MQTT discovery."""
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

        self._data = {"device": device, "apis": apis}

        entry = await self.async_set_unique_id(serial_number)
        if not entry or (CONF_ORIGINAL_DEVICE_NAME not in entry.data):
            self._data[CONF_ORIGINAL_DEVICE_NAME] = device_name

        if entry:
            name_changed = device_name != entry.title
            switching_from_local_api = CONF_URL in entry.data
            entry_data = {**entry.data, **self._data}
            entry_data.pop(CONF_URL, None)

            self.hass.config_entries.async_update_entry(
                entry,
                title=payload["device"]["name"],
                data=entry_data,
            )

            reload_required = name_changed or switching_from_local_api
            if reload_required:
                self.hass.config_entries.async_schedule_reload(entry.entry_id)

            if name_changed:
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

    async def async_step_local_api(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            use_ssl = user_input[CONF_SSL]

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

                        return self.async_create_entry(
                            title=device_name,
                            data={
                                CONF_URL: url,
                                CONF_ORIGINAL_DEVICE_NAME: device_name,
                            },
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
                }
            ),
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_local_api()

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
