# Handoff Replay Quality Review

Day 49 adds replay tests and quality review for generated handoff summaries.

## Purpose

The handoff cycle is only useful if the generated markdown is readable, concise, actionable, and loadable by the next SessionStart hook.

Day 47 generated stop-hook handoff artifacts. Day 48 loaded the latest handoff as resume context. Day 49 verifies that cycle with replay tests.

## Main files

<div dir="ltr">

| File | Purpose |
|---|---|
| `pilot_core/handoff_quality.py` | Pure quality reviewer for handoff markdown/json artifacts |
| `tests/unit/test_handoff_quality.py` | Unit tests for section and schema quality checks |
| `tests/integration/test_day49_handoff_replay_quality.py` | Replay coverage for stop -> handoff -> resume |
| `scripts/smoke_day49_handoff_quality.py` | Human-readable quality smoke report |

</div>

## Quality rules

- Required headings must exist.
- The handoff must include Task, Progress, and Next Step.
- If schema contains blockers, markdown must include Blockers.
- If schema contains do-not-redo items, markdown must include Do Not Redo.
- Empty placeholders such as `_Missing next step._` fail the review.
- Very short or very long handoffs receive warnings.
- Next Step should contain actionable language.

## Required headings

```text
# Pilot Handoff
## Task
## Progress
## Next Step
```

## Replay expectation

<div dir="ltr">

| Replay case | Expected Day 49 behaviour |
|---|---|
| healthy_session | no handoff generated |
| noisy_session | no handoff generated |
| ambiguous_session | no handoff generated |
| degraded_session | handoff generated and quality review passes |

</div>

## Artifact cycle

```text
degraded replay
  -> stop handoff result
  -> write markdown + json artifacts
  -> review both artifacts
  -> SessionStart loads latest handoff
  -> resume context is emitted as additionalContext
```

## Smoke command

```powershell
python scripts\smoke_day49_handoff_quality.py
```

## Next day

Day 50 starts Week 8 by adding tokenizer abstraction, safe stringification, and cost estimation helpers.
