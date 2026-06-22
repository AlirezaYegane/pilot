# Handoff Schema

Day 43 starts Week 7: the Handoff Engine.

## Purpose

The handoff schema is the stable data contract that later extraction and rendering code will use.

Day 43 intentionally does not read from the database, render markdown, or wire stop-hook behavior.

## Required sections

<div dir="ltr">

| Section | Meaning |
|---|---|
| `task` | What the session was trying to accomplish |
| `progress` | What has already been completed |
| `decisions` | Important decisions and rationale |
| `files_modified` | Files that were created, modified, deleted, renamed, or inspected |
| `blockers` | Unresolved issues or failures |
| `next_step` | The next concrete action for the next session |
| `do_not_redo` | Failed attempts that should not be repeated blindly |
| `notes` | Optional extra context |

</div>

## Main types

<div dir="ltr">

| Type | Purpose |
|---|---|
| `HandoffSchema` | Top-level handoff payload |
| `HandoffDecision` | Decision + rationale + rejected alternatives |
| `HandoffFileChange` | File path + status + reason |
| `HandoffBlocker` | Blocker + severity + evidence |
| `HandoffDoNotRedo` | Failed attempt + reason |

</div>

## JSON shape

```json
{
  "schema_version": "1.0",
  "session_id": "session-id",
  "generated_at": "2026-06-22T00:00:00+00:00",
  "task": "Implement Day 43 handoff schema",
  "progress": "Schema created and tested",
  "decisions": [
    {
      "title": "Keep schema separate from renderer",
      "rationale": "Markdown rendering is a later day",
      "alternatives_rejected": ["render markdown immediately"]
    }
  ],
  "files_modified": [
    {
      "path": "pilot_core/handoff.py",
      "status": "created",
      "reason": "core schema",
      "important": true
    }
  ],
  "blockers": [
    {
      "description": "DB extractor not implemented yet",
      "severity": "info",
      "evidence": "Day 44 scope"
    }
  ],
  "next_step": "Implement summary extractor from DB",
  "do_not_redo": [
    {
      "item": "Do not wire stop hook yet",
      "reason": "Stop hook integration is Day 47"
    }
  ],
  "notes": []
}
```

## Design rules

- The schema is pure and side-effect free.
- It does not query storage.
- It does not render markdown.
- It does not call hooks.
- It can round-trip through JSON.
- Validation returns errors without crashing callers.

## Smoke command

```powershell
python scripts\smoke_day43_handoff_schema.py
```
