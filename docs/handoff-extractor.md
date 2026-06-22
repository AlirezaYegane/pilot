# Handoff Summary Extractor

Day 44 adds the first data-extraction layer for the Handoff Engine.

## Scope

The extractor reads flexible DB/event records and builds a Day 43 `HandoffSchema`.

It collects:

- key turns
- signal history
- task
- progress
- lightweight decisions
- files modified or mentioned
- next step

## Out of scope

Day 44 intentionally does not implement:

- blocker extraction from failing loops
- do-not-redo extraction from repeated attempts
- markdown rendering
- stop-hook integration

Those are Day 45, Day 46, and Day 47.

## Supported sources

<div dir="ltr">

| Source | Function |
|---|---|
| In-memory records | `extract_handoff_from_records()` |
| SQLite connection | `extract_handoff_from_db()` |

</div>

## Candidate DB tables

<div dir="ltr">

| Purpose | Candidate tables |
|---|---|
| Turns/events | `session_turns`, `turns`, `events`, `session_events`, `tool_calls`, `tool_uses` |
| Signal history | `signal_results`, `session_signals`, `signals`, `signal_history` |

</div>

## Design rules

- The extractor is read-only.
- It is side-effect free except reading from a provided SQLite connection.
- It does not require a fixed storage schema yet.
- It returns a valid `HandoffSchema` even when tables are missing.
- It keeps Day 45 blocker extraction separate.
- It keeps Day 46 markdown rendering separate.

## Smoke command

```powershell
python scripts\smoke_day44_handoff_extractor.py
```

Expected smoke properties:

```text
extraction.is_valid = true
extraction.source = sqlite
key_turns includes user/summary/file records
signal_history includes fired/nonzero signals
payload_preview is a valid HandoffSchema JSON shape
```
