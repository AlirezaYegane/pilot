# Stop Hook Handoff Integration

Day 47 connects Pilot handoff generation to the Stop hook.

## Purpose

When policy runtime decides that a session should prepare a handoff, the stop-hook adapter generates a markdown handoff and optional JSON artifact.

Day 47 does not implement session-start resume flow. That belongs to Day 48.

## Pipeline

```text
Stop hook payload / signal results
  -> run_policy_runtime(at_stop_hook=True)
  -> if action mode allows prepare_handoff
  -> extract_handoff_blockers(records)
  -> build HandoffSchema
  -> render_handoff_markdown()
  -> optionally write .md and .json artifacts
```

## Main files

<div dir="ltr">

| File | Purpose |
|---|---|
| `pilot_core/stop_handoff.py` | Stop-hook handoff adapter and artifact writer |
| `hooks/stop.py` | Minimal Claude Code hook entrypoint |
| `tests/unit/test_stop_handoff.py` | Unit coverage for action/shadow/warn behavior |
| `tests/integration/test_day47_stop_handoff_replay.py` | Replay coverage |
| `scripts/smoke_day47_stop_handoff.py` | Human-readable smoke report |

</div>

## Policy behavior

<div dir="ltr">

| Condition | Result |
|---|---|
| healthy + action | no handoff |
| degraded/critical + shadow | no visible output |
| degraded/critical + warn | warning path only, handoff artifact suppressed |
| degraded/critical + action | markdown/json handoff can be generated |

</div>

## Hook safety

- The hook wrapper is intentionally tiny.
- `pilot_core.stop_handoff.main()` catches all exceptions and returns `0`.
- stdout is only used for hook JSON payloads.
- stderr is only used for user-facing warnings.
- Internal failures must not break Claude Code.

## Expected artifact names

```text
.pilot/handoffs/<session-id>-<timestamp>.md
.pilot/handoffs/<session-id>-<timestamp>.json
```

## Smoke command

```powershell
python scripts\smoke_day47_stop_handoff.py
```

## Next day

Day 48 should load the latest previous handoff from session start and expose it as resume context.
