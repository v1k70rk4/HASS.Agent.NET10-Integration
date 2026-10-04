<p align="center">
  <img src="https://raw.githubusercontent.com/v1k70rk4/HASS.Agent.NET10-Integration/refs/heads/main/custom_components/hass_agent/brand/logo%402x.png" alt="HASS.Agent Logo">
</p>

Custom Home Assistant integration for HASS.Agent devices.

This integration exposes a Windows HASS.Agent device as Home Assistant entities. Devices can connect through MQTT or Home Assistant's WebSocket API (HA API). Notification actions are exposed both as device automation triggers and as a modern Home Assistant event entity.

It is the matching Home Assistant side for the modern **HASS.Agent .NET10** Windows client.

> ⭐ **Enjoying it?** Please star this repo — and the [Windows app](https://github.com/v1k70rk4/HASS.Agent.NET10) too. It helps others find the project and keeps it going!
>
> ☕ If it saved you an evening of tinkering, you can [buy me a coffee on Ko-fi](https://ko-fi.com/v1k70rk4). Everything stays free — it just helps cover things like the code signing certificate for the Windows app.

---

> **Important**: This integration (v10.0.0+) requires **[HASS.Agent .NET10](https://github.com/v1k70rk4/HASS.Agent.NET10)** as the Windows client. The older pre-.NET10 HASS.Agent client is **not compatible** with this version: if one is detected it is not added, and a notice appears under **Settings → Repairs**. A HASS.Agent .NET10 older than the minimum below is added, with a notice to update it.
>
> The HA API WebSocket transport requires HASS.Agent .NET10 v10.2.0 or newer.
>
> If you want to keep using the old HASS.Agent client, switch to the **[`legacy` branch](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/tree/legacy)** of this integration. The legacy branch works with Home Assistant 2026.6+ and the original pre-.NET10 HASS.Agent, but it is **no longer maintained**.

> **Stable:** [10.7.3](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/releases/latest) &nbsp;·&nbsp; **Beta:** [10.9.0-beta.2](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/releases/tag/v10.9.0-beta.2) &nbsp;·&nbsp; [What changed](#changelog) &nbsp;·&nbsp; [Full changelog](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/blob/main/CHANGELOG.md)

---

## Installation

### Requirements

| Component | Minimum version |
|-----------|----------------|
| Home Assistant | 2026.6.0 |
| HASS.Agent .NET10 (Windows client) | 10.2.0 (10.9.0+ recommended) |
| MQTT broker (recommended) | Mosquitto or any MQTT 3.1.1+ broker |

HACS is required for installation. This integration is available in the **HACS default store**, so no custom repository needs to be added.

MQTT is recommended for full functionality. Alternatively, HA API (WebSocket) provides nearly the same features without requiring an MQTT broker. The Local HTTP API setup supports notifications only.

### Install from HACS

This integration is in the **HACS default store** — no custom repository needed.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=v1k70rk4&repository=HASS.Agent.NET10-Integration&category=integration)

1. Open **HACS** and search for **HASS.Agent** — or click the button above.
2. **Download** the integration.
3. **Restart** Home Assistant.
4. **Add the integration** — click the button below (or go to **Settings → Devices & services → Add integration → HASS.Agent**):

   [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hass_agent)

   With MQTT enabled in the Windows client — or over the HA API (WebSocket), as soon as the client connects — the PC turns up on its own under **Discovered** at the top of **Settings → Devices & services**. Like any Home Assistant discovery it waits for you: click **Add** on that card to create the device and its entities. For the Local HTTP API you always add it manually here.

<details>
<summary>Manual install (custom repository fallback)</summary>

If the integration isn't showing in your HACS yet, add it as a custom repository: **HACS → ⋮ menu → Custom repositories**, URL `https://github.com/v1k70rk4/HASS.Agent.NET10-Integration`, category **Integration**.
</details>

If another HASS.Agent integration is already installed, remove it before installing this one, then restart Home Assistant.

---

## Features

- MQTT auto-discovery for HASS.Agent .NET10 devices
- Media player entity for playback control, volume control, media browsing, TTS, and album art
- Notify entity for sending notifications to the Windows client
- Notification action triggers for automations
- Notification action event entity for newer Home Assistant automation workflows
- Button entities for Windows commands: lock, sleep, monitor off, volume, shutdown, restart, restart cancel
- Custom command button entities: user-defined programs, PowerShell scripts, key presses, links and popup windows advertised by the Windows client
- System sensor entities for Windows machine state (CPU, memory, disk, battery, network, session, etc.)
- Custom sensor entities: process running, service status, disk free, built-in attribute extraction, command output, LibreHardwareMonitor values
- Dynamic sensor handling based on what the Windows client advertises
- Automatic removal of disabled command and sensor entities
- Service-aware command routing for system commands handled by the Windows service
- HA API WebSocket failover transport for device, sensor, media, and notification action events
- Serial-number based MQTT topic and HA API command routing
- `hass_agent.execute_command` service for scripts and automations
- In the 10.9.0 beta: the PC's display as a light, select entities for the default audio output and input device, a *Hotkeys* event entity, and the `hass_agent.set_app_volume` service
- Local HTTP API setup for notification-only use cases (with API key authentication)
- Hungarian and English translations

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

Nearly all features work — notifications, media player, sensors, commands — with some trade-offs compared to MQTT:

- No retained state (sensor values are lost until the agent reconnects after a restart)
- No Last Will (no automatic offline detection)
- Media thumbnails are ~33% larger (base64 encoding)
- HTTPS is required for remote access

The Windows service takes part on this transport too (client 10.6.5+): it announces itself on its own event, and command buttons are routed to the app or the service exactly as they are over MQTT.

The client communicates through Home Assistant's event bus:

```text
hass_agent_device_update          # discovery + capabilities (tray app)
hass_agent_service_update         # Windows service status + capabilities
hass_agent_update_state           # available app update (drives the update entity)
hass_agent_sensor_update          # sensor values
hass_agent_media_update           # media player state
hass_agent_media_thumbnail        # media album art (base64)
hass_agent_notification_action    # notification button press
hass_agent_hotkey                 # hotkey press (client 10.9.0+)
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
| `event` | Notification actions, Hotkeys | Action button press events from notifications; hotkey presses (client 10.9.0+) |
| `sensor` | System sensors | Built-in and custom sensors from the Windows client |
| `button` | System commands | Lock, sleep, shutdown, restart, volume, etc. |
| `select` | Audio output / input | Chooses the default playback and recording device (client 10.9.0+, the matching *Audio output device* / *Audio input device* sensor enabled) |
| `light` | Display | Screen brightness where the display can be dimmed; off switches the monitor off, on wakes it (client 10.9.0+, *Display brightness* sensor enabled) |
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

What can go under the inner `data`:

| Field | Description |
|-------|-------------|
| `actions` | Buttons, each with an `action` (what comes back) and a `title`. Up to five. |
| `image` | A picture: a web address, a path on this Home Assistant (`/local/doorbell.jpg`, `/api/camera_proxy/camera.front_door`), or a camera or image entity (`camera.front_door`). A path or an entity is signed for five minutes so the PC can fetch it. Client 10.9.0+. |
| `inputs` | Text fields, each with an `id` and a `title` (the hint in the empty field). Up to five. What was typed comes back with the pressed button, in `input`, by id. Client 10.9.0+. |
| `duration` | Seconds on screen, 1 to 60 (default 10). |
| `style` | `toast` (a Windows notification) or `window` (the client's own always-visible window), for this one notification. Without it the client's own setting decides. Client 10.9.0+. |

> `image`, `inputs` and `style` are in the 10.9.0 beta (integration and client 10.9.0-beta.2 or newer). An older client shows the notification without them.

```yaml
action: hass_agent.send_notification
target:
  entity_id: notify.my_pc_notifications
data:
  title: Doorbell
  message: "Somebody is at the front door."
  data:
    image: camera.front_door
    style: window
    inputs:
      - id: answer
        title: "Say something through the intercom"
    actions:
      - action: speak
        title: "Speak"
```

The press arrives on the device's *Notification actions* event entity and as a `hass_agent_notifications` event, with the typed text in `input`:

```yaml
action: speak
input:
  answer: "Leave it at the door, please"
device_name: MY-PC
```

### hass_agent.execute_command

Sends a system command to a HASS.Agent .NET10 device:

| Field | Required | Description |
|-------|:--------:|-------------|
| `device_name` | yes | Target Windows device name |
| `command` | * | `lock`, `sleep`, `hibernate`, `logoff`, `monitor_off`, `volume_up`, `volume_down`, `toggle_mute`, `shutdown`, `restart` |
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

### hass_agent.set_app_volume

> In the 10.9.0 beta. Needs the Windows client 10.9.0-beta.1 or newer with its *Audio sessions* sensor turned on.

Sets the volume of one app in the Windows volume mixer, or mutes it. The *Audio sessions* sensor lists the apps with their volumes as attributes.

| Field | Required | Description |
|-------|:--------:|-------------|
| `device_name` | yes | Target Windows device name |
| `app` | yes | The app as the *Audio sessions* sensor names it, e.g. `spotify` |
| `volume` | * | Volume in percent, `0` to `100` |
| `muted` | * | `true` to mute, `false` to unmute |

\* At least one of `volume` and `muted` is required; both can be given in one call.

```yaml
action: hass_agent.set_app_volume
data:
  device_name: MY-PC
  app: spotify
  volume: 30
```

## MQTT Topics

Published by the Windows client, consumed by this integration:

```text
hass.agent/devices/{serialNumber}                # discovery + capabilities
hass.agent/system/{serialNumber}/state           # Windows service status
hass.agent/sensors/{serialNumber}/state          # sensor values
hass.agent/update/{serialNumber}/state           # app update state
hass.agent/media_player/{serialNumber}/state     # media player state
hass.agent/notifications/{serialNumber}/actions  # notification action events
hass.agent/hotkeys/{serialNumber}/pressed        # hotkey presses (client 10.9.0+)
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

A hotkey pressed on the PC (client 10.9.0+) reaches the device's *Hotkeys* event entity on either transport, and the entity fires `hass_agent_hotkey_pressed` on the event bus with the hotkey's name in `hotkey`.

---

## Changelog

### 10.9.0-beta.2

> **Beta.** A pre-release: in HACS, open the integration, choose **Redownload**, turn on **Show beta versions**, then pick **10.9.0-beta.2** in the version list. It goes with the Windows client **10.9.0-beta.2**. The current stable release is **10.7.3**, below.

**New since beta.1**

- **Pictures in notifications, straight from Home Assistant.** `image` in a notification's `data` can now be a path on this Home Assistant (`/local/doorbell.jpg`, `/api/camera_proxy/camera.front_door`) or simply a camera or image entity (`camera.front_door`). The integration signs the address for five minutes, so the PC can fetch the picture without a login of its own; it sends both the internal and the external address of this Home Assistant, and the PC uses the one it can reach. A full web address is passed on as it is. Showing the picture needs the Windows client **10.9.0-beta.2** or newer.
- **Text typed into a notification comes back.** The client 10.9.0-beta.2 can show text fields (`inputs`) on a notification; what was typed arrives with the pressed button, as `input` in the data of the *Notification actions* event and of the `hass_agent_notifications` bus event.
- The integration now names `http` as a dependency, which the signed picture addresses need.
- **Fixed: a custom sensor with a unit and a value that is not a number no longer floods the log.** Home Assistant takes a sensor with a unit for a number and raised an error on every update when the value was a text such as `off`. Such a sensor now shows as unknown, and the log says once which sensor it is and what to change in the Windows client.

**From beta.1**

- **Audio device selects.** Two select entities choose the PC's default playback and recording device, from the list of devices Windows has active. The output one appears for every client **10.9.0** or newer whose *Audio output device* sensor is on (it is by default); the input one when the new *Audio input device* sensor is turned on.
- **Hotkeys as events.** A client 10.9.0+ with hotkeys set up gets a *Hotkeys* event entity whose event types are the hotkey names, for automations that start from the keyboard. The press also fires `hass_agent_hotkey_pressed` on the event bus.
- **`hass_agent.set_app_volume` service.** Sets the volume or mute of one app in the Windows volume mixer (client 10.9.0+ with its *Audio sessions* sensor on; the sensor lists the apps with their volumes as attributes).
- **Hibernate and Log off buttons**, for clients 10.9.0+ that have the command enabled (both are off by default in the client).
- **The PC's display as a light.** With the Windows client **10.9.0** or newer and its *Display brightness* sensor turned on (tray app), the device gets a *Display* light: the brightness slider sets the screen brightness, off switches the monitor off, on wakes it. The client adjusts the built-in panel of a laptop and external monitors that speak DDC/CI; with no adjustable display (many TVs) the light is a plain on/off one. Works over MQTT and the HA API. The light disappears again when the sensor is turned off.

### 10.7.3

- **A *Check for updates* button next to the update entity.** It makes the Windows client ask GitHub right away instead of waiting for its six-hourly check, so a fresh release shows up in Home Assistant at once. Needs HASS.Agent .NET10 **10.7.3** or newer (an older client ignores the command). Thanks to [@Taomyn](https://github.com/Taomyn) for the idea.
- **One update entity, on both transports.** Over MQTT the update entity came from Home Assistant's own MQTT discovery and over the HA API from this integration, so a PC that switched transports ended up with two, one of them always unavailable. The integration now builds the entity on MQTT as well and tells the client so (a retained message on `hass.agent/integration/{id}`); a client 10.7.3 or newer removes its discovered one in return. With an older client the discovered entity stays and the integration leaves it alone. The entity now follows the whole device rather than the tray app, so it stays available while only the service runs, and *Install* works with nobody logged in (client 10.7.3+).
- The media player image is served with the right content type (the client sends JPEG covers since 10.7.2).
- The issue templates link to the renamed client repository.

Older versions are in the [changelog](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/blob/main/CHANGELOG.md).

---

## Legacy Branch

> **Using the old pre-.NET10 HASS.Agent?** Install **[v3.0.2](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/releases/tag/v3.0.2)** from HACS: open *HASS.Agent .NET10 Integration* in HACS, choose *Redownload* and pick version `v3.0.2`. HACS otherwise installs the latest release (10.x), which cannot talk to the old client — you would see a **Settings → Repairs** notice saying the PC was not added, and nothing else would happen.
>
> v3.0.2 is compatible with **Home Assistant 2026.6+** and the original pre-.NET10 HASS.Agent client. It is **no longer maintained** — updating the Windows client to HASS.Agent .NET10 is the way forward.
>
> Documentation and usage instructions for v3.0.2 are available on the **[`legacy` branch](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/tree/legacy)**.
>
> The `main` branch (v10.0.0+) is designed exclusively for **HASS.Agent .NET10** and is not backwards compatible with the old client.
