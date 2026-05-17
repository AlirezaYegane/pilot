# SessionStart Hook

Day 16 implements the first real Pilot hook.

## Purpose

`SessionStart` creates or reopens a local session record when Claude Code starts, resumes, or clears a session.

## Files

- `hooks/session_start.py`
- `pilot_core/hook_handlers/session_start.py`
- `tests/integration/test_session_start_hook.py`

## Behaviour

The hook:

- reads JSON from stdin
- parses `session_id`
- records `cwd`, `model`, and optional `parent_session_id`
- creates or reopens a row in `sessions`
- exits with status code `0` even if Pilot fails internally

## Idempotency

Repeated `SessionStart` events for the same session do not create duplicate rows.

The original `started_at` value is preserved.

If the same session is reopened, `ended_at` is reset to `NULL`.

## Safety

This hook must never break the user's Claude Code session.

Errors are swallowed and logged through Pilot's local debug logger.

## Design rule

The public hook file must stay thin.

Business logic belongs in:

- `pilot_core/hook_handlers/session_start.py`

This keeps the hook easy to test and keeps Claude Code runtime behaviour safe.
