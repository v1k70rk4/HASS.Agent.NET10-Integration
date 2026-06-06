<p align="center">
  <img src="https://raw.githubusercontent.com/v1k70rk4/HASS.Agent-Integration/refs/heads/main/custom_components/hass_agent/brand/logo%402x.png" alt="HASS.Agent Logo">
</p>
Custom Home Assistant integration for HASS.Agent devices.

This integration exposes a Windows HASS.Agent device as Home Assistant entities. Devices can be discovered through MQTT, and notification actions are exposed both as device automation triggers and as a modern Home Assistant event entity.

It is the matching Home Assistant side for the modern **HASS.Agent .NET10** Windows client.

The modern .NET10-compatible integration line starts at **version 10.0.0**. The pre-.NET10 integration remains available on the `legacy` branch for users who do not want to migrate to the .NET10 client yet.

## Features

- MQTT auto-discovery for HASS.Agent devices
- Media player entity for playback control, volume control, media browsing, TTS, and album art
- Notify entity for sending notifications to the Windows client
- Notification action triggers for automations
- Notification action event entity for newer Home Assistant automation workflows
- Button entities for Windows commands such as lock, sleep, monitor off, volume, shutdown, restart, and restart cancel
- System sensor entities for Windows machine state
- Dynamic standard/custom sensor handling based on what the Windows client advertises
- Automatic removal of disabled command and sensor entities
- Service-aware command routing for system commands handled by the Windows service
- `hass_agent.execute_command` service for scripts and automations
- Local API setup for notification-only use cases
- Hungarian and English translations

## Requirements

- Home Assistant 2026.6.0 or newer
- MQTT integration configured in Home Assistant
- HACS, when installing through the custom repository flow
- A compatible HASS.Agent client, recommended: **HASS.Agent .NET10**

MQTT discovery is recommended when you want media player support. The Local API setup currently supports notifications only.

## Installation

1. Open HACS in Home Assistant.
2. Add this repository as a custom integration repository:

   ```text
   https://github.com/v1k70rk4/HASS.Agent-Integration
   ```

3. Install **HASS.Agent Integration** from HACS.
4. Restart Home Assistant.
5. Configure discovered HASS.Agent devices from **Settings > Devices & services**.

If another HASS.Agent integration is already installed, remove it before installing this one, then restart Home Assistant.

## HASS.Agent .NET10 Support

The integration understands the MQTT payloads published by HASS.Agent .NET10:

```text
hass.agent/devices/{deviceName}
hass.agent/system/{deviceName}/state
hass.agent/sensors/{deviceName}/state
hass.agent/media_player/{deviceName}/state
hass.agent/notifications/{deviceName}/actions
```

Command topics:

```text
hass.agent/buttons/{deviceName}/cmd
hass.agent/system/{deviceName}/cmd
```

When the Windows client changes its enabled features, the integration reloads the affected platforms and removes entities that are no longer advertised.

## Services

### hass_agent.send_notification

Sends a notification to a HASS.Agent notify entity. Action buttons can be passed in the `data.actions` object.

### hass_agent.execute_command

Sends a command to a HASS.Agent .NET10 device.

Supported fields:

- `device_name`: target Windows device name
- `command`: `lock`, `sleep`, `monitor_off`, `volume_up`, `volume_down`, `toggle_mute`, `shutdown`, or `restart`
- `comment`: optional Windows shutdown/restart comment
- `force`: adds forced shutdown/restart behavior on the Windows side
- `time`: delay in seconds
- `restart_cancel`: cancels a pending shutdown/restart

Example:

```yaml
action: hass_agent.execute_command
data:
  device_name: RV-NOTE
  command: restart
  force: true
  time: 30
  comment: Home Assistantból újraindítva
```

Cancel a pending shutdown or restart:

```yaml
action: hass_agent.execute_command
data:
  device_name: RV-NOTE
  restart_cancel: true
```

## Version 10.0.0

This release adds HASS.Agent .NET10 support:

- Added command button entities
- Added system sensor entities
- Added dynamic standard/custom sensor discovery
- Added sensor attributes for richer Windows state
- Added service-aware command routing
- Added `hass_agent.execute_command`
- Added shutdown/restart parameters: `comment`, `force`, `time`, and `restart_cancel`
- Added inactive entity removal when a feature is disabled in the Windows client

## Legacy Branch

If you want to keep using the old pre-.NET10 HASS.Agent client, use the `legacy` branch instead of this modern line.

## Previous 3.x Line

This release modernizes the integration for Home Assistant 2026.6 and newer.

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
