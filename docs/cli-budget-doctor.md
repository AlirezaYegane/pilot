# Day 54 CLI Budget and Doctor

Day 54 adds two daily-use CLI commands:

- `pilot budget`
- `pilot doctor`

## Scope

Day 54 does not redesign the existing `status`, `sessions`, or `show` commands. It adds budget and diagnostics commands while preserving the previous CLI through `pilot_core/cli_legacy.py`.

## `pilot budget`

`pilot budget` exposes the Day 51 budget engine through the CLI.

It can read usage records from a Pilot SQLite database or a JSONL fixture.

```powershell
pilot budget
pilot budget --json
pilot budget --db .pilot\pilot.db
pilot budget --fixture tests\fixtures\replay_cases\degraded_session.jsonl --json
```

## `pilot doctor`

`pilot doctor` checks install, database, and hook health.

```powershell
pilot doctor
pilot doctor --json
pilot doctor --db .pilot\pilot.db
pilot doctor --no-fail
```

## Diagnostics

<div dir="ltr">

| Area | Checks |
|---|---|
| Install | Python version, package import, pyproject, plugin manifest |
| DB | DB path, SQLite connection, tables, journal mode |
| Hooks | hooks directory, hooks.json parse, required hook files, Python syntax |

</div>

## Design rules

- Broken runtime state should not crash the CLI.
- Missing DB is a warning, not a hard failure.
- Broken hook syntax is a failure.
- Existing CLI commands are preserved through `cli_legacy.py`.
- `budget` uses the existing Day 51 budget engine.

## Quality gate

```powershell
ruff check . --fix
ruff format .
mypy pilot_core tests scripts
pytest tests\unit\test_day54_cli_budget_doctor.py
pytest tests\integration\test_day54_cli_diagnostics.py
python scripts\smoke_day54_budget_doctor.py
pytest
pre-commit run --all-files
```
