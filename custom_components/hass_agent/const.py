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
# Options: the media player shows the PC as off instead of unavailable and can be turned
# on and off. Both fire a device trigger and run an optional script; turn off can also
# run one of the PC's own commands.
CONF_MEDIA_PLAYER_POWER = "media_player_power"
CONF_MEDIA_PLAYER_TURN_OFF = "media_player_turn_off"
CONF_MEDIA_PLAYER_TURN_ON_SCRIPT = "media_player_turn_on_script"
CONF_MEDIA_PLAYER_TURN_OFF_SCRIPT = "media_player_turn_off_script"
# With the Windows service still reporting the PC is on and only the app is closed: the
# player is unavailable then, not off.
CONF_MEDIA_PLAYER_SERVICE_STATE = "media_player_service_state"
MEDIA_PLAYER_TURN_OFF_NONE = "none"
MEDIA_PLAYER_TURN_OFF_COMMANDS = ("sleep", "hibernate", "shutdown")
EVENT_TURN_ON_REQUESTED = "hass_agent_turn_on_requested"
EVENT_TURN_OFF_REQUESTED = "hass_agent_turn_off_requested"
CONF_RESTART_CANCEL = "restart_cancel"
CONF_TIME = "time"

# The Home Assistant user a PC on the HA API speaks as, when that user is not an
# administrator (see ws_commands). Set when an administrator approves the PC.
CONF_USER_ID = "user_id"
# The user hass_agent/provision made for the PC: the only one it ever gives a token again.
CONF_PROVISIONED_USER_ID = "provisioned_user_id"
# The same user, carried in the data of a discovery the approval is asked in.
DISCOVERY_USER_ID = "hass_agent_user_id"
# A PC waiting for approval announced itself; the manual HA API step listens for it.
SIGNAL_PENDING_DEVICE = "hass_agent_pending_device"

EVENT_NOTIFICATION_ACTIONS = "hass_agent_notifications"

SIGNAL_BUTTONS_UPDATED = "hass_agent_buttons_updated_{}"
SIGNAL_SENSORS_UPDATED = "hass_agent_sensors_updated_{}"
SIGNAL_UPDATE_STATE = "hass_agent_update_state_{}"
