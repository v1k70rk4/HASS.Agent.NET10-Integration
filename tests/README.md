# Tests

The integration's tests run on Home Assistant itself, through
[pytest-homeassistant-custom-component](https://github.com/MatthieuDartiailh/pytest-homeassistant-custom-component):
a Home Assistant instance in memory, with a mocked MQTT client, no network and no real PC.

| File | What it covers |
|------|----------------|
| `test_notify.py` | the notification action: fields of their own winning over `data`, pictures on this Home Assistant signed and sent with the internal and the external address, MQTT and HA API delivery |
| `test_sensor.py` | custom sensors: values of every kind, texts cut to the state limit, a text with a unit turning into unknown with a single log line |
| `test_services.py` | the actions are registered and refuse bad input |
| `test_init.py` | the announce request to HA API clients, after Home Assistant has started or a moment after a reload |

They need Linux (or WSL) and Python 3.14, like Home Assistant:

```bash
python -m pip install -r requirements_test.txt
python -m pytest
```

GitHub Actions runs them on every pull request and on main (`.github/workflows/tests.yaml`).
Every bug fix comes with a test that fails without the fix.
