# Security Policy

## Supported versions

| Version | Security fixes |
|---------|----------------|
| Latest release ([Releases](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/releases/latest)) | Yes |
| The beta running at the time, if there is one | Yes |
| Older 10.x versions | No, please update first |
| v3.0.2 on the [`legacy` branch](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/tree/legacy) | No, it is no longer maintained |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it privately instead:

**[Report a vulnerability](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/security/advisories/new)** (the *Security* tab of this repository, *Report a vulnerability*).

Only you and the maintainer see the report. It helps to include:

- the version of the integration, of Home Assistant and of the Windows client,
- the transport (MQTT, HA API, local HTTP API),
- what someone could do with it, and under which conditions,
- the steps to reproduce it.

You get an answer within a few days. Once it is fixed, the release notes mention it and thank you by name, unless you would rather not be named. Where it is warranted, a GitHub security advisory (and a CVE) is published with the fix.

## What counts

Anything that lets someone do more than the person who set up Home Assistant intended, for example:

- the **services** (`hass_agent.execute_command`, `hass_agent.send_notification`, `hass_agent.set_app_volume`) and the buttons that make a PC run something,
- the **picture addresses** the integration signs for a notification (signed for five minutes, so the PC can fetch the picture without a login of its own),
- the **messages from the PC** over MQTT and the HA API, and what the integration builds from them,
- the **stored settings** of a config entry, such as the API key of the local HTTP API.

Not in scope: problems in Home Assistant, the MQTT broker or Windows themselves; something that needs an administrator account in Home Assistant already. The Windows client has its own [security policy](https://github.com/v1k70rk4/HASS.Agent.NET10/security/policy); a report sent to either repository reaches the same person.
