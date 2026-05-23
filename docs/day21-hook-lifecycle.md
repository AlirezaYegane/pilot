# Day 21: Stop and SessionEnd Hook Lifecycle

Day 21 closes the basic Week 3 hook plumbing milestone.

## Implemented

- `pilot_core/hook_lifecycle.py`
- `hooks/stop.py`
- `hooks/session_end.py`
- `scripts/smoke_day21_hooks.py`

## Behaviour

### Stop

The Stop hook:

- reads the hook payload from stdin
- extracts `session_id`
- writes a handoff placeholder under the local handoff directory
- updates `handoff_summary_path` when the sessions table supports it
- emits `additionalContext` only when the session is already in a handoff-worthy state

### SessionEnd

The SessionEnd hook:

- reads the hook payload from stdin
- extracts `session_id`
- writes a handoff placeholder
- updates `ended_at`
- exits safely

## Safety contract

Both wrappers must always return exit code `0`, even if the payload is malformed or the local database is unavailable.

Pilot must never break the user's active Claude Code session.

## Validation

Run:

```powershell
python scripts/smoke_day21_hooks.py
ruff format .
ruff check . --fix
mypy pilot_core tests
pytest
pre-commit run --all-files
