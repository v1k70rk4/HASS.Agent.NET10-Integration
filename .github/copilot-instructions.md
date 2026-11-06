# Copilot code review instructions

- Start review comments with a short, one-sentence summary of the suggested fix.
- Do not comment on code style, formatting or linting issues. Ruff, pinned in `.github/workflows/ruff.yaml`, runs `ruff check` in CI; `ruff format` is not part of this project, so do not ask for it.
- Flag comments that over-explain straightforward code, narrate the obvious, or read like AI commentary (multi-sentence justifications for a single line).
- A pull request with a dependency version bump should only contain changes required for the version bump. If the PR includes other changes, request that they are removed from the PR. Dependabot PRs are identifiable by "Dependabot commands and options" in their description.
- The version numbers (`manifest.json`, the status line and requirements table of `README.md`) and the changelog (`CHANGELOG.md`, the `## Changelog` section of `README.md`) change only in a release pull request. In any other pull request, ask for them to be left alone.
- Text a user sees goes into every file under `custom_components/hass_agent/translations/` under the same key. A language the author does not speak may carry the English text, with a note in the PR. In a translation PR, check keys and `{placeholders}` against `en.json`; grammar and tone in that language are the translator's.
- Anything that comes from a PC or from the MQTT broker is untrusted input. A PC must not be able to act for another PC, send its notifications elsewhere, reach files or addresses outside what it is meant to, or do more than its own Home Assistant user may. `tests/test_hardening.py` and `tests/test_ws_commands.py` show the bar; a change that touches what comes in over MQTT, the HA API or the local HTTP endpoints should keep it.
- A bug fix comes with a test that fails without the fix; new behaviour gets tests in the same pull request. Ask for the test when it is missing.
- There is no PR template. Check that the description says what the change does and why, and for a bug, how to reproduce it.
- CodeRabbit reviews every pull request too. Do not repeat its comments; a point it already made and the author answered needs no second thread.

# GitHub Copilot & Claude Code Instructions

This repository is a custom integration for Home Assistant, `custom_components/hass_agent`, the Home Assistant side of HASS.Agent .NET10 (a Windows client). It is installed from the Marketplace (HACS before Home Assistant 2026.11), not part of Home Assistant core, and it has to run on every Home Assistant from 2026.6 on.

## Git Commit Guidelines

- **Do NOT amend, squash, or rebase commits that have already been pushed to the PR branch after the PR is opened.** Reviewers need to follow the commit history, as well as see what changed since their last review. Pull requests are squash-merged at the end.

## Pull Requests

- One change per pull request, against `main`. Say what it changes and why; for a bug, how to reproduce it.
- Leave the version numbers and the changelog alone; they are updated when a release is made.

## Development Commands

- Lint: `ruff check custom_components/hass_agent`, with the ruff version pinned in `.github/workflows/ruff.yaml`.
- Tests: `python -m pip install -r requirements_test.txt` then `python -m pytest`. They run on Home Assistant itself through `pytest-homeassistant` (Home Assistant's own test package), so they need Linux or WSL and the Python version that Home Assistant uses (3.14.2 or newer at the time of writing); see `tests/README.md`.
- `hassfest` and the HACS validation run in CI (`.github/workflows/hassfest.yaml`, `validate.yaml`); there is no local script for them.

## Python Syntax Notes

- The integration runs on every Home Assistant from 2026.6 on, so the code must work on the Python of that release (3.13). Do not use, or suggest, syntax that needs Python 3.14 in the integration itself. The tests run on the Python of the pinned `pytest-homeassistant` and may use what it supports.
- Modules use `from __future__ import annotations`; forward references in annotations need no quoting.

## Testing

- The tests run against a Home Assistant instance in memory, with a mocked MQTT client, no network and no real PC. A test that needs the network or a running PC is wrong.
- When writing or modifying tests, ensure all test function parameters have type annotations.
- Prefer concrete types (for example, `HomeAssistant`, `MockConfigEntry`, etc.) over `Any`.
- Prefer `@pytest.mark.usefixtures` over arguments, if the argument will not be used.
- Avoid using conditions/branching in tests. Instead, either split tests or adjust the test parametrization to cover all cases without branching.
- If multiple tests share most of their code, use `pytest.mark.parametrize` to merge them into a single parameterized test instead of duplicating the body. Use `pytest.param` with an `id` parameter to name the test cases clearly.
- Hardcoded `entity_id`s in tests are fine. If the same one is repeated, use a constant.
- Every bug fix comes with a test that fails without the fix.

## Good practices

- Integrations with Platinum or Gold level in Home Assistant's Integration Quality Scale reflect a high standard of code quality and maintainability. When looking for examples of something, these are good places to start. The level is indicated in the `manifest.json` of the integration in Home Assistant core.
- When reviewing entity actions, do not suggest extra defensive checks for input fields that are already validated by Home Assistant's service/action schemas and entity selection filters. Suggest additional guards only when data bypasses those validators or is transformed into a less-safe form.
- When validation guarantees a dict key exists, prefer direct key access (`data["key"]`) instead of `.get("key")` so contract violations are surfaced instead of silently masked.
- Keep comments concise. Prefer one short line stating the non-obvious constraint, or no comment at all.
- Do not add comments that just restate the code on the following line(s) (e.g. `# Check if initialized` above `if self.initialized:`). Comments should only explain why (non-obvious constraints, surprising behavior, or workarounds), never what. Never add comments that justify a change by referencing what the code looked like before. Comments in tests that explain why a function call or assertion is made are ok.
- Do not add section or divider comments (e.g. `# --- XYZ Triggers ---`) inside or outside of functions, since those can easily become stale and be misleading.
- When catching exceptions, try-clauses should be as small as possible, i.e. avoid wrapping large blocks of code in a try-clause, and avoid catching exceptions from functions that are not expected to raise them.
- Asserts that exist only to narrow types for the type checker must be placed behind an `if TYPE_CHECKING:` guard, so they are not executed at runtime.
- Sensitive service actions, i.e. those that can change configuration or have security implications, should require an admin user. Register them with the `async_register_admin_service` service helper, which checks this for you.
- Constants that more than one module of the integration uses go in `const.py`; a constant only one module uses stays in that module. Tests do not count as a user. This includes entity descriptions and service schemas. Never import a constant from one platform module into another; move it to `const.py` instead. Pre-existing constants that a change does not touch can stay where they are.
- What comes from a PC (MQTT payloads, HA API commands, the local HTTP endpoints) is untrusted: validate it, keep a PC to its own device and its own Home Assistant user, and never let a value from it name a file, a host or another PC. Log a rejected value once, without the secret in it.
