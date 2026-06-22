# Handoff Blocker Extraction

Day 45 adds blocker extraction for Pilot handoff summaries.

## Purpose

The blocker extractor turns raw session/tool records into structured `blockers` and `do_not_redo` items for the handoff schema.

Day 45 intentionally does not render markdown and does not wire the stop hook. Markdown rendering is Day 46, and stop-hook integration is Day 47.

## What it detects

<div dir="ltr">

| Pattern | Meaning | Output |
|---|---|---|
| failing loop | Same attempt fails consecutively | `HandoffBlocker` + `HandoffDoNotRedo` |
| repeated attempt | Same attempt appears repeatedly and includes failures | `HandoffBlocker` + `HandoffDoNotRedo` |
| failure density | Multiple failures without one clean loop | warning `HandoffBlocker` |

</div>

## Default thresholds

```text
window_size = 30 recent events
failing_loop_threshold = 3 consecutive failures
repeated_attempt_threshold = 3 attempts with at least one failure
critical_loop_threshold = 4 consecutive failures
```

## Main API

<div dir="ltr">

| Function | Purpose |
|---|---|
| `normalise_handoff_attempt_event()` | Convert raw hook/replay record into a common attempt event |
| `find_failing_loops()` | Detect consecutive failed loops |
| `find_repeated_attempts()` | Detect repeated retry patterns |
| `extract_handoff_blockers()` | Produce blockers and do-not-redo items |
| `handoff_blocker_extraction_summary()` | Compact smoke/CLI summary |

</div>

## Design rules

- The module is pure and side-effect free.
- It does not read from SQLite directly.
- It does not render markdown.
- It only returns handoff-schema-compatible records.
- Single transient failures should not create aggressive handoff blockers.

## Example output

```json
{
  "blocker_count": 2,
  "do_not_redo_count": 2,
  "failing_loop_count": 1,
  "repeated_attempt_count": 1,
  "has_blockers": true
}
```
