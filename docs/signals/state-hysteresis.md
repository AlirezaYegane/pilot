# State Hysteresis

Day 38 adds hysteresis and anti-flapping behavior to the Pilot session state machine.

## Why this exists

Without hysteresis, a session with health near a boundary can flip repeatedly between adjacent states.
For example, scores around `0.80` could cause repeated `healthy <-> watching` transitions.

The main Pilot plan recommends a 5% buffer to keep transitions smooth and reliable.

## Health bands

```text
health >= 0.80 -> healthy
0.60 <= health < 0.80 -> watching
0.40 <= health < 0.60 -> degrading
health < 0.40 -> critical
```

## Hysteresis rules

```text
healthy -> watching only when health < 0.80 - 0.05
watching -> healthy only when health >= 0.80 + 0.05
watching -> degrading only when health < 0.60 - 0.05
degrading -> watching only when health >= 0.60 + 0.05
degrading -> critical only when health < 0.40 - 0.05
critical -> degrading only when health >= 0.40 + 0.05
```

## API

```text
hysteresis_state_from_health_score(current_state, health_score)
transition_session_state_with_hysteresis(current_state, health_score=...)
transition_from_health_with_hysteresis(current_state, health)
apply_hysteresis_sequence(initial_state, health_scores)
```

## Compatibility

The deterministic Day 37 API remains available:

```text
state_from_health_score(health_score)
transition_session_state(current_state, health_score=...)
transition_from_health(current_state, health)
```

## Smoke command

```powershell
python scripts\smoke_day38_state_hysteresis.py
```
