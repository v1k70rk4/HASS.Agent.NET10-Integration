<p align="center">
  <img src="https://raw.githubusercontent.com/v1k70rk4/HASS.Agent.NET10-Integration/refs/heads/main/custom_components/hass_agent/brand/logo%402x.png" alt="HASS.Agent Logo">
</p>

Custom Home Assistant integration for HASS.Agent devices.

This integration exposes a Windows HASS.Agent device as Home Assistant entities. Devices can connect through MQTT or Home Assistant's WebSocket API (HA API). Notification actions are exposed both as device automation triggers and as a modern Home Assistant event entity.

It is the matching Home Assistant side for the modern **HASS.Agent .NET10** Windows client.

---

> **Important**: This integration (v10.0.0+) requires **[HASS.Agent .NET10](https://github.com/v1k70rk4/HASS.Agent)** as the Windows client. The older pre-.NET10 HASS.Agent client is **not compatible** with this version.
>
> The HA API WebSocket transport requires HASS.Agent .NET10 v10.2.0 or newer.
>
> If you want to keep using the old HASS.Agent client, switch to the **[`legacy` branch](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/tree/legacy)** of this integration. The legacy branch is compatible with Home Assistant 2026.6+ and the original pre-.NET10 HASS.Agent.

---

## Features

- MQTT auto-discovery for HASS.Agent .NET10 devices
- Media player entity for playback control, volume control, media browsing, TTS, and album art
- Notify entity for sending notifications to the Windows client
- Notification action triggers for automations
- Notification action event entity for newer Home Assistant automation workflows
- Button entities for Windows commands: lock, sleep, monitor off, volume, shutdown, restart, restart cancel
- System sensor entities for Windows machine state (CPU, memory, disk, battery, network, session, etc.)
- Custom sensor entities: process running, service status, disk free, built-in attribute extraction
- Dynamic sensor handling based on what the Windows client advertises
- Automatic removal of disabled command and sensor entities
- Service-aware command routing for system commands handled by the Windows service
- HA API WebSocket failover transport for device, sensor, media, and notification action events
- Serial-number based MQTT topic and HA API command routing
- `hass_agent.execute_command` service for scripts and automations
- Local HTTP API setup for notification-only use cases (with API key authentication)
- Hungarian and English translations

## Requirements

| Component | Minimum version |
|-----------|----------------|
| Home Assistant | 2026.6.0 |
| HASS.Agent .NET10 (Windows client) | 10.2.0 |
| MQTT broker (recommended) | Mosquitto or any MQTT 3.1.1+ broker |

HACS is required when installing through the custom repository flow.

MQTT is recommended for full functionality. Alternatively, HA API (WebSocket) provides nearly the same features without requiring an MQTT broker. The Local HTTP API setup supports notifications only.

## Installation

1. Open HACS in Home Assistant.
2. Add this repository as a custom integration repository:

   ```text
   https://github.com/v1k70rk4/HASS.Agent.NET10-Integration
   ```

3. Install **HASS.Agent Integration** from HACS.
4. Restart Home Assistant.
5. The device appears automatically if MQTT is enabled in the Windows client. If using HA API (WebSocket) only, the device registers when the Windows client connects. For Local HTTP API, add the device manually from **Settings > Devices & services > Add integration > HASS.Agent**.

If another HASS.Agent integration is already installed, remove it before installing this one, then restart Home Assistant.

## Connection Modes

### MQTT (recommended)

Enable MQTT in the HASS.Agent .NET10 Windows client. The device is discovered automatically in Home Assistant. All features work:

- Notifications (with actionable buttons)
- Media player (play/pause, volume, TTS)
- System sensors (built-in + custom)
- Command buttons (lock, shutdown, restart, etc.)
- Update entity
- Windows service integration
- Retained state on restart
- Last Will (automatic offline detection)

### HA API (WebSocket)

The Windows client connects directly to Home Assistant's WebSocket API using a long-lived access token. Works remotely (e.g. via Nabu Casa) without an MQTT broker. Can be used standalone or as automatic failover when the MQTT broker is unreachable.

Nearly all features work — notifications, media player, sensors, commands, update entity — with some trade-offs compared to MQTT:

- No retained state (sensor values are lost until the agent reconnects after a restart)
- No Last Will (no automatic offline detection)
- Media thumbnails are ~33% larger (base64 encoding)
- No Windows service integration
- HTTPS is required for remote access

The client communicates through Home Assistant's event bus:

```text
hass_agent_device_update          # discovery + capabilities
hass_agent_sensor_update          # sensor values
hass_agent_media_update           # media player state
hass_agent_media_thumbnail        # media album art (base64)
hass_agent_notification_action    # notification button press
```

All events and commands are targeted by `serial_number`, so renaming a device in Home Assistant does not break command delivery.

### Local HTTP API

A minimal fallback for environments where neither MQTT nor HA API is available. Add the device manually:

- **Host**: the Windows machine's LAN IP address
- **Port**: `5115` (default)
- **SSL**: disabled
- **API key**: copy from the agent's General settings page (Network section)

Only notifications are supported. The `POST /notify` endpoint is protected with the API key (`Authorization: Bearer <key>`). Use MQTT or HA API for full functionality.

## Entities

When connected via MQTT or HA API, the integration creates the following entities:

| Platform | Entity | Description |
|----------|--------|-------------|
| `media_player` | Media player | Control Windows media playback, volume, TTS |
| `notify` | Notifications | Send notifications to the Windows tray |
| `event` | Notification actions | Action button press events from notifications |
| `sensor` | System sensors | Built-in and custom sensors from the Windows client |
| `button` | System commands | Lock, sleep, shutdown, restart, volume, etc. |
| `update` | App update | Shows available HASS.Agent .NET10 updates |

Entities are created and removed dynamically as the Windows client changes its configuration.

## Services

### hass_agent.send_notification

Sends a notification to a HASS.Agent notify entity. Supports actionable notifications with buttons:

```yaml
action: hass_agent.send_notification
target:
  entity_id: notify.my_pc_notifications
data:
  message: "Would you like to turn on the lights?"
  title: Home Assistant
  data:
    actions:
      - action: lights_on
        title: "Turn on"
      - action: lights_off
        title: "Turn off"
```

### hass_agent.execute_command

Sends a system command to a HASS.Agent .NET10 device:

| Field | Required | Description |
|-------|:--------:|-------------|
| `device_name` | yes | Target Windows device name |
| `command` | * | `lock`, `sleep`, `monitor_off`, `volume_up`, `volume_down`, `toggle_mute`, `shutdown`, `restart` |
| `comment` | | Windows shutdown/restart comment |
| `force` | | Force shutdown/restart (default: `false`) |
| `time` | | Delay in seconds (default: `0`) |
| `restart_cancel` | * | Cancel a pending shutdown/restart |

\* Either `command` or `restart_cancel: true` is required.

Example:

```yaml
action: hass_agent.execute_command
data:
  device_name: MY-PC
  command: restart
  force: true
  time: 30
  comment: "Restarted from Home Assistant"
```

Cancel a pending shutdown or restart:

```yaml
action: hass_agent.execute_command
data:
  device_name: MY-PC
  restart_cancel: true
```

When the Windows service is online and capable of handling the command, the integration automatically routes it to the service topic. Otherwise it falls back to the tray app.

## MQTT Topics

Published by the Windows client, consumed by this integration:

```text
hass.agent/devices/{serialNumber}                # discovery + capabilities
hass.agent/system/{serialNumber}/state           # Windows service status
hass.agent/sensors/{serialNumber}/state          # sensor values
hass.agent/update/{serialNumber}/state           # app update state
hass.agent/media_player/{serialNumber}/state     # media player state
hass.agent/notifications/{serialNumber}/actions  # notification action events
```

Published by this integration (commands):

```text
hass.agent/notifications/{serialNumber}          # outgoing notifications
hass.agent/media_player/{serialNumber}/cmd       # media player commands
hass.agent/buttons/{serialNumber}/cmd            # system command buttons
hass.agent/system/{serialNumber}/cmd             # service-routed commands
```

## Home Assistant Events

When using the HA API (WebSocket) transport, the Windows client fires events into Home Assistant's event bus instead of MQTT topics (see [HA API (WebSocket)](#ha-api-websocket) above). The integration also sends commands back to the client through the `hass_agent_command` event:

```json
{
  "serial_number": "device-serial-number",
  "command_type": "button_command",
  "payload": {
    "command": "restart",
    "force": true,
    "time": 30
  }
}
```

## Legacy Branch

> **Using the old pre-.NET10 HASS.Agent?** Install **[v3.0.2](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/releases/tag/v3.0.2)** from HACS (available in the releases).
>
> v3.0.2 is compatible with **Home Assistant 2026.6+** and the original pre-.NET10 HASS.Agent client. It will continue to receive compatibility fixes but no new features.
>
> Documentation and usage instructions for v3.0.2 are available on the **[`legacy` branch](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/tree/legacy)**.
>
> The `main` branch (v10.0.0+) is designed exclusively for **HASS.Agent .NET10** and is not backwards compatible with the old client.

## Changelog

### 10.4.0

- Added device availability: entities now turn **unavailable** when the device disconnects — via the MQTT availability topic / Last Will, and via a heartbeat timeout on the HA API WebSocket transport
- Added `enum` device class with possible-value options for the monitor power state, power status, and session state sensors, so Home Assistant knows their selectable states
- Fully backwards compatible — these activate with HASS.Agent .NET10 v10.4.0 or newer; older clients keep working unchanged

### 10.3.0

- Added persistent notification support: the device can create Home Assistant persistent notifications (update progress, update completed, errors) over MQTT and the HA API WebSocket transport
- Fully backwards compatible — the notification feature activates with HASS.Agent .NET10 v10.3.0 or newer, older clients work unchanged

### 10.2.0

- Added standalone HA API auto-discovery so devices can be added without an MQTT broker
- Added `async_step_ha_api` config flow and user menu with HA API info and Local API options
- Fixed `event.py` missing WebSocket dispatcher listener for notification actions
- Updated all entity platforms to skip MQTT operations for HA API-only entries

### 10.1.0

- Added HA API WebSocket transport handling for device, sensor, media, thumbnail, and notification action events
- Added serial-number based MQTT topic and WebSocket command routing so Home Assistant device renames do not break commands
- Updated button, media player, notification, and service command fallbacks to route commands with `serial_number`
- Documented the HA API WebSocket mode and its event payloads
- Bumped the integration version to 10.1.0

### 10.0.0

HASS.Agent .NET10 support:

- Added command button entities
- Added system sensor entities (built-in + custom)
- Added dynamic standard/custom sensor discovery
- Added sensor attributes for richer Windows state
- Added service-aware command routing
- Added `hass_agent.execute_command` service
- Added shutdown/restart parameters: `comment`, `force`, `time`, `restart_cancel`
- Added inactive entity removal when features are disabled in the Windows client
- Added API key authentication for Local HTTP API mode

### 3.x (pre-.NET10)

- Replaced the custom unauthenticated thumbnail endpoint with Home Assistant's built-in media player image proxy
- Added a notification action event entity
- Improved config entry setup retry behavior
- Improved platform unload handling
- Hardened MQTT and config flow payload parsing
- Updated MQTT publish calls with explicit `qos` and `retain`
- Updated media source typing for Home Assistant 2026.6
- Added Ruff linting workflow
- Enabled hassfest and HACS validation on push and pull request
- Added Hungarian translations


