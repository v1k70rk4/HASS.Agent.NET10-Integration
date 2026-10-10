# Tests

The integration's tests run on Home Assistant itself, through
[pytest-homeassistant-custom-component](https://github.com/MatthieuDartiailh/pytest-homeassistant-custom-component):
a Home Assistant instance in memory, with a mocked MQTT client, no network and no real PC.

| File | What it covers |
|------|----------------|
| `test_notify.py` | the notification action: fields of their own winning over `data`, pictures on this Home Assistant signed and sent with the internal and the external address, MQTT and HA API delivery |
| `test_sensor.py` | custom sensors: values of every kind, texts cut to the state limit, a text with a unit turning into unknown with a single log line |
| `test_services.py` | the actions are registered and refuse bad input |
| `test_init.py` | the announce request waits until Home Assistant has started |
| `test_setup.py` | a PC on the HA API set up, reloaded and unloaded the way Home Assistant does it, and the announce request a moment after each setup |
| `test_hardening.py` | what a PC, or anything that can publish to the broker, must not be able to do: speak for another PC, take its name, send its notifications elsewhere, link a release outside GitHub, have a picture path signed that is not one |
| `test_ws_commands.py` | the HA API commands for a PC with a Home Assistant user of its own: approval of a new user, only its own events and commands, the user an administrator creates for it, never a token for a person's account |

They need Linux (or WSL) and Python 3.14, like Home Assistant:

```bash
python -m pip install -r requirements_test.txt
python -m pytest
```

GitHub Actions runs them on every pull request and on main (`.github/workflows/tests.yaml`).
Every bug fix comes with a test that fails without the fix.
