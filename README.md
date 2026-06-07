<p align="center">
  <img src="https://raw.githubusercontent.com/v1k70rk4/HASS.Agent-Integration/refs/heads/main/custom_components/hass_agent/brand/logo%402x.png" alt="HASS.Agent Logo">
</p>

Custom Home Assistant integration for HASS.Agent devices.

This integration exposes a Windows HASS.Agent device as Home Assistant entities. Devices can be discovered through MQTT, and notification actions are exposed both as device automation triggers and as a modern Home Assistant event entity.

It is the matching Home Assistant side for the modern **HASS.Agent .NET10** Windows client.

---

> **Important**: This integration (v10.0.0+) requires **[HASS.Agent .NET10](https://github.com/v1k70rk4/HASS.Agent)** as the Windows client. The older pre-.NET10 HASS.Agent client is **not compatible** with this version.
>
> If you want to keep using the old HASS.Agent client, switch to the **[`legacy` branch](https://github.com/v1k70rk4/HASS.Agent-Integration/tree/legacy)** of this integration. The legacy branch is compatible with Home Assistant 2026.6+ and the original pre-.NET10 HASS.Agent.

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
- `hass_agent.execute_command` service for scripts and automations
- Local API setup for notification-only use cases (with API key authentication)
- Hungarian and English translations

## Requirements

| Component | Minimum version |
|-----------|----------------|
| Home Assistant | 2026.6.0 |
| HASS.Agent .NET10 (Windows client) | 10.0.0 |
| MQTT broker | Mosquitto or any MQTT 3.1.1+ broker |

HACS is required when installing through the custom repository flow.

MQTT discovery is recommended for full functionality. The Local API setup supports notifications only.

## Installation

1. Open HACS in Home Assistant.
2. Add this repository as a custom integration repository:

   ```text
   https://github.com/v1k70rk4/HASS.Agent-Integration
   ```

3. Install **HASS.Agent Integration** from HACS.
4. Restart Home Assistant.
5. The device appears automatically if MQTT is enabled in the Windows client. Otherwise add it manually from **Settings > Devices & services > Add integration > HASS.Agent**.

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

### Local API

For environments where MQTT is not available. Add the device manually:

- **Host**: the Windows machine's LAN IP address
- **Port**: `5115` (default)
- **SSL**: disabled
- **API key**: copy from the agent's General settings page (Network section)

Only notifications are supported in Local API mode. The `POST /notify` endpoint is protected with the API key (`Authorization: Bearer <key>`).

## Entities

When connected via MQTT, the integration creates the following entities:

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
hass.agent/devices/{deviceName}                  # discovery + capabilities
hass.agent/system/{deviceName}/state             # Windows service status
hass.agent/sensors/{deviceName}/state            # sensor values
hass.agent/update/{deviceName}/state             # app update state
hass.agent/media_player/{deviceName}/state       # media player state
hass.agent/notifications/{deviceName}/actions    # notification action events
```

Published by this integration (commands):

```text
hass.agent/notifications/{deviceName}            # outgoing notifications
hass.agent/media_player/{deviceName}/cmd         # media player commands
hass.agent/buttons/{deviceName}/cmd              # system command buttons
hass.agent/system/{deviceName}/cmd               # service-routed commands
```

## Legacy Branch

> **Using the old pre-.NET10 HASS.Agent?** Switch to the **[`legacy` branch](https://github.com/v1k70rk4/HASS.Agent-Integration/tree/legacy)**.
>
> The legacy branch is compatible with **Home Assistant 2026.6+** and the original pre-.NET10 HASS.Agent client. It will continue to receive compatibility fixes but no new features.
>
> The `main` branch (v10.0.0+) is designed exclusively for **HASS.Agent .NET10** and is not backwards compatible with the old client.

## Changelog

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
- Added API key authentication for Local API mode

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

## Credits

This project builds on the work done by:

- [hass-agent/HASS.Agent-Integration](https://github.com/hass-agent/HASS.Agent-Integration)
- [LAB02-Research/HASS.Agent-Integration](https://github.com/LAB02-Research/HASS.Agent-Integration)

Thanks to the original maintainers and contributors for creating the foundation this integration is based on.
