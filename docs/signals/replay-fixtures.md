# Replay Fixture Scenarios

Day 34 adds scenario-level replay fixtures for validating Pilot signal behavior before threshold tuning.

## Fixture directory

```text
tests/fixtures/replay_cases/
```

## Cases

| Fixture | Purpose | Expected behavior |
|---|---|---|
| `healthy_session.jsonl` | Normal implementation flow | No signals should fire |
| `degraded_session.jsonl` | Clear degradation pattern | Multiple core signals should fire |
| `noisy_session.jsonl` | Natural tool noise and one-off retry | At most one signal should fire |
| `ambiguous_session.jsonl` | Mild pressure but recoverable | Scores may rise, but aggressive firing should stay limited |

## Why this exists

Unit tests prove each detector works in isolation. Replay fixtures test whether the same detectors behave sensibly on mixed session streams.

These fixtures are not threshold tuning yet. Day 35 uses them for the full 8-signal integration pass and false-positive review.

## Design rules

- Healthy cases must stay quiet.
- Degraded cases must produce clear signal pressure.
- Noisy cases protect against false positives.
- Ambiguous cases protect against over-aggressive escalation.
- Fixtures should stay small enough for hot-path replay tests.

## Smoke command

```powershell
python scripts\smoke_day34_replay_fixtures.py
```

## Test command

```powershell
pytest tests\integration\test_day34_replay_fixtures.py
```
