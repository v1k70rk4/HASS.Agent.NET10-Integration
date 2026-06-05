# HASS.Agent Integration

Custom Home Assistant integration for HASS.Agent devices.

This integration exposes a Windows HASS.Agent device as a Home Assistant media player and notification target. Devices can be discovered through MQTT, and notification actions are exposed both as device automation triggers and as a modern Home Assistant event entity.

## Features

- MQTT auto-discovery for HASS.Agent devices
- Media player entity for playback control, volume control, media browsing, TTS, and album art
- Notify entity for sending notifications to the Windows client
- Notification action triggers for automations
- Notification action event entity for newer Home Assistant automation workflows
- Local API setup for notification-only use cases
- Hungarian and English translations

## Requirements

- Home Assistant 2026.6.0 or newer
- MQTT integration configured in Home Assistant
- HACS, when installing through the custom repository flow
- A compatible HASS.Agent client

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

## Version 3.0.0

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
