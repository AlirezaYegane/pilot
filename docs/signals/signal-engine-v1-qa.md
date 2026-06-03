# Signal Engine v1 QA

Day 27 hardens the first four Pilot degradation signals.

## Scope

- repeated_calls
- error_cascade
- token_burn
- context_saturation

## Why this day exists

The first four signals now exist individually. Day 27 checks that they also behave consistently as a group.

## Shared result contract

Every signal result should provide:

- signal_name
- score between 0.0 and 1.0
- confidence between 0.0 and 1.0
- severity
- explanation
- optional fired property

## Edge cases covered

- empty input
- missing fields
- malformed numeric values
- threshold boundary behavior
- replay fixtures

## Replay fixtures

```text
tests/fixtures/repeated_calls.jsonl
tests/fixtures/error_cascade.jsonl
tests/fixtures/token_burn.jsonl
tests/fixtures/context_bloat.jsonl
```

## Commands

```powershell
pytest tests/unit/test_signal_engine_v1_contracts.py
pytest tests/integration/test_signal_engine_v1_replay.py
python scripts/smoke_day27_signals.py
```

## Notes

- Day 27 does not tune thresholds.
- Day 27 does not introduce new user-facing alerts.
- Signal behavior must remain local, pure, and cheap.
- Any threshold change should wait for broader replay evidence.
