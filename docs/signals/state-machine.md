# Session State Machine

Day 37 adds Pilot session-state transitions.

## Scope

This day implements the deterministic state machine only. Hysteresis and boundary anti-flapping tests are intentionally left for Day 38.

## States

<div dir="ltr">

| State | Meaning |
|---|---|
| healthy | Session is safe and quiet |
| watching | Mild pressure, still no user-facing action |
| degrading | Quality is dropping and escalation may be needed |
| critical | Strong degradation signal pressure |
| handoff_pending | Handoff should be prepared or completed |
| handed_off | Terminal state for the old session |

</div>

## Health bands

```text
health >= 0.80 -> healthy
0.60 <= health < 0.80 -> watching
0.40 <= health < 0.60 -> degrading
health < 0.40 -> critical
```

## Transition rules

- `handed_off` is terminal unless a forced state is supplied.
- `handoff_completed` moves any active session to `handed_off`.
- `handoff_requested` moves `degrading` or `critical` sessions to `handoff_pending`.
- `handoff_pending` stays pending until completed or forced.
- Otherwise, state follows the current health band.

## Why no hysteresis today?

The roadmap keeps Day 37 and Day 38 separate. Day 37 creates the stable state-machine contract. Day 38 adds hysteresis, boundary tests, and anti-flapping behavior.

## Smoke command

```powershell
python scripts\smoke_day37_state_machine.py
```
