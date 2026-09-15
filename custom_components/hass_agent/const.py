"""Constants for the HASS.Agent integration."""

DOMAIN = "hass_agent"

# Oldest HASS.Agent .NET10 client this integration supports. Kept in step with the
# requirements table in README.md; the client has the mirror image of this check
# (MinimumIntegrationVersion) for the integration.
MINIMUM_CLIENT_VERSION = "10.2.0"
CLIENT_RELEASES_URL = "https://github.com/v1k70rk4/HASS.Agent.NET10/releases/latest"

CONF_ACTION = "action"
CONF_API_KEY = "api_key"
CONF_HA_API = "ha_api"
CONF_COMMENT = "comment"
CONF_COMMAND = "command"
CONF_DEVICE_NAME = "device_name"
CONF_DEFAULT_NOTIFICATION_TITLE = "default_notification_title"
CONF_FORCE = "force"
CONF_ORIGINAL_DEVICE_NAME = "original_device_name"
CONF_RESTART_CANCEL = "restart_cancel"
CONF_TIME = "time"

EVENT_NOTIFICATION_ACTIONS = "hass_agent_notifications"

SIGNAL_BUTTONS_UPDATED = "hass_agent_buttons_updated_{}"
SIGNAL_SENSORS_UPDATED = "hass_agent_sensors_updated_{}"
SIGNAL_UPDATE_STATE = "hass_agent_update_state_{}"
