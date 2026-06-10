# Day 35 Full 8-Signal Integration Review

Day 35 validates all eight Pilot degradation signals together against the Day 34 replay fixtures.

## Goal

The goal is not to add another signal. The goal is to prove that the existing signal set behaves sensibly as a combined detector before health scoring starts.

## Signals covered

- token_burn
- repeated_calls
- error_cascade
- backtracking
- context_saturation
- self_doubt
- rate_limit
- low_productivity

## Replay cases

| Case | Expected behavior |
|---|---|
| healthy_session | 0 fired signals |
| noisy_session | at most 1 fired signal |
| ambiguous_session | at most 2 fired signals, no expensive resource alarms |
| degraded_session | at least 5 fired signals |

## False-positive policy

- Healthy sessions must stay completely quiet.
- Noisy sessions may show mild score pressure, but should not produce broad firing.
- Ambiguous sessions may show warning-level pressure, but should not trigger resource-related alarms.
- Degraded sessions must show clear multi-signal pressure.

## Threshold tuning result

Day 35 does not globally lower thresholds. The current policy is conservative: protect healthy/noisy/ambiguous sessions from over-triggering and require degraded sessions to fire several independent signals.

## Test command

```powershell
pytest tests\integration\test_day35_full_signal_integration.py
```

## Smoke command

```powershell
python scripts\smoke_day35_signal_tuning.py
```

## Next step

Day 36 can safely implement combined health scoring using these replay expectations as guardrails.
