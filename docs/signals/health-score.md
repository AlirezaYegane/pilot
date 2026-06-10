# Health Score Computation

Day 36 adds the combined health scoring layer for Pilot.

The signal modules already return individual `score`, `confidence`, and `fired` values. The health layer combines those signal outputs into one session-level score.

## Formula

```text
raw_badness = sum(signal_score * signal_weight)

if fired_count >= 3:
    adjusted_badness = raw_badness * 1.30
else:
    adjusted_badness = raw_badness

health_score = clamp(1.0 - adjusted_badness, 0.0, 1.0)
```

## Default weights

<div dir="ltr">

| Signal | Weight |
|---|---:|
| token_burn | 0.15 |
| repeated_calls | 0.20 |
| error_cascade | 0.20 |
| backtracking | 0.10 |
| context_saturation | 0.15 |
| self_doubt | 0.10 |
| rate_limit | 0.25 |
| low_productivity | 0.10 |

</div>

## State bands

<div dir="ltr">

| Health score | Derived state |
|---:|---|
| >= 0.80 | healthy |
| >= 0.60 and < 0.80 | watching |
| >= 0.40 and < 0.60 | degrading |
| < 0.40 | critical |

</div>

## Design notes

- The health score uses signal scores as badness scores.
- Missing signals contribute zero badness.
- Multiple simultaneous fired signals increase adjusted badness.
- This module only computes the state band; actual state transitions and hysteresis remain in the state machine layer.
- The result includes top contributors so CLI/status views can explain why health dropped.

## Smoke command

```powershell
python scripts\smoke_day36_health_score.py
```
