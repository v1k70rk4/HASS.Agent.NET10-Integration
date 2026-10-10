# Contributing

Thanks for wanting to help. Bug reports, ideas and pull requests are all welcome.

## Questions, bugs and ideas

Open an [issue](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/issues/new/choose) and pick the template that fits. For a bug, the versions of the integration, Home Assistant and the Windows client, the connection mode (MQTT or HA API) and the Home Assistant log lines for `custom_components.hass_agent` help the most.

Problems on the Windows side (the tray app, sensors, commands, the service) belong to the [client](https://github.com/v1k70rk4/HASS.Agent.NET10/issues). Not sure which one? Open it here, it will be moved.

**Security problems are not reported in issues.** See [SECURITY.md](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/blob/main/SECURITY.md) for the private way.

## Pull requests

1. Fork the repository and branch off `main`.
2. Keep a pull request to one change. Say what it changes and why; for a bug, how to reproduce it.
3. Open the pull request against `main`. CI runs ruff, the tests, hassfest, the HACS validation and CodeQL, and it gets a review before it is merged.

Before you open it:

- **Ruff is clean:** `ruff check custom_components/hass_agent`, with the version pinned in `.github/workflows/ruff.yaml`.
- **The tests pass:** see [tests/README.md](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/blob/main/tests/README.md). They need Linux or WSL and the Python version Home Assistant uses.
- **A bug fix comes with a test** that fails without the fix. New behaviour gets tests in the same pull request.
- **Text the user sees** goes into both `translations/en.json` and `translations/hu.json`. If you don't speak Hungarian, put the English text in both and say so; it will be translated.
- **Anything that comes from a PC or the MQTT broker is untrusted input.** A PC must not be able to act for another PC, reach files or addresses outside what it is meant to, or do more than its own Home Assistant user may. `tests/test_hardening.py` shows what that means in practice.
- **Leave the version numbers and the changelog alone.** They are updated when a release is made.

## License

By contributing you agree that your contribution is released under the project's [MIT License](https://github.com/v1k70rk4/HASS.Agent.NET10-Integration/blob/main/LICENSE).
