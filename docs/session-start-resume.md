# SessionStart Resume Flow

Day 48 connects Pilot handoff artifacts to the SessionStart hook.

## Purpose

When a previous session generated a handoff, the next Claude Code session should automatically receive that handoff as resume context.

Day 47 wrote markdown and JSON handoff artifacts. Day 48 loads the latest artifact and emits hook-safe `additionalContext` from SessionStart.

## Pipeline

```text
SessionStart payload
  -> resolve handoff directory
  -> find latest .json/.md handoff artifact
  -> prefer JSON when available
  -> render markdown from HandoffSchema
  -> emit {"additionalContext": "..."}
```

## Main files

<div dir="ltr">

| File | Purpose |
|---|---|
| `pilot_core/session_resume.py` | Load latest handoff and build resume context |
| `hooks/session_start.py` | Minimal SessionStart hook wrapper |
| `tests/unit/test_session_resume.py` | Unit coverage for artifact loading |
| `tests/integration/test_day48_session_resume.py` | Day 47 artifact to Day 48 resume test |
| `scripts/smoke_day48_session_resume.py` | Human-readable smoke report |

</div>

## Artifact rules

- `.json` is preferred because it can be validated and re-rendered.
- `.md` is accepted as a fallback.
- Invalid JSON is skipped rather than crashing the hook.
- Missing handoff directory produces no output.
- Long resume context is bounded before being emitted.

## Hook safety

- SessionStart must always return exit code `0`.
- stdout is only used for control JSON.
- Internal failures emit nothing.
- The hook also keeps the lightweight earlier session-start DB bootstrap behavior.

## Expected stdout shape

```json
{
  "additionalContext": "Pilot resume context from previous handoff\\n..."
}
```

## Smoke command

```powershell
python scripts\smoke_day48_session_resume.py
```

## Next day

Day 49 should add handoff replay tests and quality review over generated summaries.
