# Changelog

Every release of the HASS.Agent .NET10 integration, newest first. The Windows client has its own [changelog](https://github.com/v1k70rk4/HASS.Agent.NET10/blob/main/CHANGELOG.md).

## Unreleased

- **Fixed: a PC that only uses the HA API showed old data after a Home Assistant restart.** Its device was set up from what the integration stored on the day the PC was added (the version and the capabilities of that day), and the client's fresh data, sent the moment it reconnected, arrived before the integration listened. The device page showed an old firmware version, the update entity was unavailable, and capabilities gained since could be missing until the client announced itself again. The integration now keeps the latest device data, and asks the client to announce itself once Home Assistant has started (the client answers from 10.9.0 on; the stored data alone already helps with older ones).
- **Fixed for good: "has already been setup" errors.** Capability messages arriving in a burst were handled side by side and could set a platform up twice or unload it mid-setup. They are applied one at a time now, the latest winning.

## 10.9.0-beta.2

> **Beta.** A pre-release: in HACS, open the integration, choose **Redownload**, turn on **Show beta versions**, then pick **10.9.0-beta.2** in the version list. It goes with the Windows client **10.9.0-beta.2**. The current stable release is **10.7.3**, below.

**New since beta.1**

- **Pictures in notifications, straight from Home Assistant.** `image` in a notification's `data` can now be a path on this Home Assistant (`/local/doorbell.jpg`, `/api/camera_proxy/camera.front_door`) or simply a camera or image entity (`camera.front_door`). The integration signs the address for five minutes, so the PC can fetch the picture without a login of its own; it sends both the internal and the external address of this Home Assistant, and the PC uses the one it can reach. A full web address is passed on as it is. Showing the picture needs the Windows client **10.9.0-beta.2** or newer.
- **Text typed into a notification comes back.** The client 10.9.0-beta.2 can show text fields (`inputs`) on a notification; what was typed arrives with the pressed button, as `input` in the data of the *Notification actions* event and of the `hass_agent_notifications` bus event.
- The integration now names `http` as a dependency, which the signed picture addresses need.
- **Fixed: "has already been setup" errors at a Home Assistant start.** Two capability messages of one PC arriving back to back (the retained one and the client's fresh one) could both start setting up the same platform; Home Assistant refused the second with an error in the log, once per platform. The entities were there all the same.
- **Fixed: a custom sensor with a unit and a value that is not a number no longer floods the log.** Home Assistant takes a sensor with a unit for a number and raised an error on every update when the value was a text such as `off`. Such a sensor now shows as unknown, and the log says once which sensor it is and what to change in the Windows client.

**From beta.1**

- **Audio device selects.** Two select entities choose the PC's default playback and recording device, from the list of devices Windows has active. The output one appears for every client **10.9.0** or newer whose *Audio output device* sensor is on (it is by default); the input one when the new *Audio input device* sensor is turned on.
- **Hotkeys as events.** A client 10.9.0+ with hotkeys set up gets a *Hotkeys* event entity whose event types are the hotkey names, for automations that start from the keyboard. The press also fires `hass_agent_hotkey_pressed` on the event bus.
- **`hass_agent.set_app_volume` service.** Sets the volume or mute of one app in the Windows volume mixer (client 10.9.0+ with its *Audio sessions* sensor on; the sensor lists the apps with their volumes as attributes).
- **Hibernate and Log off buttons**, for clients 10.9.0+ that have the command enabled (both are off by default in the client).
- **The PC's display as a light.** With the Windows client **10.9.0** or newer and its *Display brightness* sensor turned on (tray app), the device gets a *Display* light: the brightness slider sets the screen brightness, off switches the monitor off, on wakes it. The client adjusts the built-in panel of a laptop and external monitors that speak DDC/CI; with no adjustable display (many TVs) the light is a plain on/off one. Works over MQTT and the HA API. The light disappears again when the sensor is turned off.

## 10.7.3

- **A *Check for updates* button next to the update entity.** It makes the Windows client ask GitHub right away instead of waiting for its six-hourly check, so a fresh release shows up in Home Assistant at once. Needs HASS.Agent .NET10 **10.7.3** or newer (an older client ignores the command). Thanks to [@Taomyn](https://github.com/Taomyn) for the idea.
- **One update entity, on both transports.** Over MQTT the update entity came from Home Assistant's own MQTT discovery and over the HA API from this integration, so a PC that switched transports ended up with two, one of them always unavailable. The integration now builds the entity on MQTT as well and tells the client so (a retained message on `hass.agent/integration/{id}`); a client 10.7.3 or newer removes its discovered one in return. With an older client the discovered entity stays and the integration leaves it alone. The entity now follows the whole device rather than the tray app, so it stays available while only the service runs, and *Install* works with nobody logged in (client 10.7.3+).
- The media player image is served with the right content type (the client sends JPEG covers since 10.7.2).
- The issue templates link to the renamed client repository.

## 10.7.0

- **Five new sensors from the Windows client** (HASS.Agent .NET10 **10.7.0** or newer). They are switched off in the client until you enable them on its *Sensors* page, and only then appear in Home Assistant:
  - **GPU usage** — GPU load in percent, as Task Manager shows it, on Intel, AMD and NVIDIA alike. Attributes: load per engine (`3d`, `videodecode`, …), NPU load, dedicated / shared memory in use, the installed adapters.
  - **Sleep blocked** — `on` while something keeps the PC or its display awake; the attributes name what (`primary_blocker`, `blockers`).
  - **Last wake reason** — what woke the PC last (`Input Keyboard`, `Power Button`, `Lid`, a device, a wake timer…), with the time, how long it was away and whether it really slept.
  - **Camera in use** / **Microphone in use** — `on` while an app uses the camera or the microphone, with the apps in the `apps` attribute.
- **No more deprecation warnings at startup.** Home Assistant logged four of them at every start (`device_registry.async_get_device` … *will stop working in Home Assistant 2027.8.0*). The device lookup now uses the replacement on Home Assistant 2026.8 and newer, and keeps working on 2026.6 / 2026.7.
- **Nothing changes for existing devices.** Entities are only created for the sensors a client advertises, so no new entity appears until you enable a sensor in the client, and older clients keep working exactly as before.

## 10.6.8

- **The old HASS.Agent client is no longer added as a broken device.** The original pre-.NET10 client sends a discovery message of the same shape, so it used to pass validation and turn up as a device that could never work properly — a notify entity that would not come back, for example. Discovery now checks the client's version: the old client is not added, and a notice under **Settings → Repairs** explains that the Windows client needs updating to HASS.Agent .NET10. A HASS.Agent .NET10 older than **10.2.0** is still added, with a notice to update it. Either notice disappears on its own once the client is updated.
- The legacy line of this integration (v3.x) is **no longer maintained**.

Works with every supported HASS.Agent .NET10 client; no client update is needed for this release.

## 10.6.7

- **A PC can now be added over the HA API (WebSocket) transport without MQTT.** Automatic discovery only ever worked once the integration was already set up, which left the *first* device unable to arrive on its own — and MQTT was no help to the people most likely to be affected, since HA API is the transport you choose when Home Assistant is not on your local network. **Settings → Devices & services → Add integration → HASS.Agent → HA API** now waits for the PC to announce itself and adds it.
- **The update entity works on the HA API transport.** It came from Home Assistant's own MQTT discovery, so without a broker there was no update entity and no Install button. The integration now builds it from the agent's own events. Requires HASS.Agent .NET10 **10.6.7** or newer.

## 10.6.6

- **The tray app and the Windows service are now treated as two independent providers.** Previously only the tray app published the device's availability, so closing it (or logging out) turned *everything* unavailable — including sensors the service was still happily reporting. The device now stays reachable while either side is running, and each entity follows whichever side actually feeds it: tray-only entities (media player, active window, notifications) go **unavailable** instead of disappearing, and return as soon as it is back.
- **A provider that stops no longer has its entities deleted.** Entity creation is now independent of whether the side that offers it happens to be running, so its entities stay in place and simply grey out. Turning a capability off in the Windows client still removes those entities, as before. Requires HASS.Agent .NET10 **10.6.6** or newer.

## 10.6.5

- Added a **service channel for the HA API (WebSocket) transport**. Over MQTT the tray app and the Windows service each announce what they can handle on their own topic, and this integration merges the two — the WebSocket had no equivalent, so the service had to announce itself as the app. It now has its own event, and button presses name the side they are meant for, so a command runs exactly once and on the right side even when the tray app is not running. Requires HASS.Agent .NET10 **10.6.5** or newer; older clients keep working as before.

## 10.6.0

- Added **custom command buttons**: programs and PowerShell scripts you define in the Windows client (10.6.0+) now appear as button entities. The client advertises only each command's id and name; pressing the button asks the client to run the command you defined — Home Assistant never sends the underlying program or script. Buttons route to the tray app or the Windows service depending on where the command is enabled, and are removed automatically when the client stops advertising them.

## 10.5.0

- Fixed a spurious "received invalid discovery payload" warning: the device availability sub-topic (`hass.agent/devices/<serial>/availability`) matches the same MQTT discovery wildcard and is no longer treated as a discovery message

## 10.4.0

- Added device availability: entities now turn **unavailable** when the device disconnects — via the MQTT availability topic / Last Will, and via a heartbeat timeout on the HA API WebSocket transport
- Added `enum` device class with possible-value options for the monitor power state, power status, and session state sensors, so Home Assistant knows their selectable states
- Fully backwards compatible — these activate with HASS.Agent .NET10 v10.4.0 or newer; older clients keep working unchanged

## 10.3.0

- Added persistent notification support: the device can create Home Assistant persistent notifications (update progress, update completed, errors) over MQTT and the HA API WebSocket transport
- Fully backwards compatible — the notification feature activates with HASS.Agent .NET10 v10.3.0 or newer, older clients work unchanged

## 10.2.0

- Added standalone HA API auto-discovery so devices can be added without an MQTT broker
- Added `async_step_ha_api` config flow and user menu with HA API info and Local API options
- Fixed `event.py` missing WebSocket dispatcher listener for notification actions
- Updated all entity platforms to skip MQTT operations for HA API-only entries

## 10.1.0

- Added HA API WebSocket transport handling for device, sensor, media, thumbnail, and notification action events
- Added serial-number based MQTT topic and WebSocket command routing so Home Assistant device renames do not break commands
- Updated button, media player, notification, and service command fallbacks to route commands with `serial_number`
- Documented the HA API WebSocket mode and its event payloads
- Bumped the integration version to 10.1.0

## 10.0.0

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

## 3.x (pre-.NET10)

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
