# Decision Engine

Day 39 adds Pilot policy decisions on top of health scoring and the hysteresis-safe state machine.

## Purpose

The decision engine converts a state transition into a concrete action: stay silent, observe, inject Claude context, notify the user, or prepare handoff.

## Inputs

- `StateTransition` from the state machine
- optional `HealthComputation` for health score and top signal contributors
- optional turn cooldown metadata
- hook context such as `at_stop_hook`

## State behavior

<div dir="ltr">

| State | Decision behavior |
|---|---|
| healthy | silent |
| watching | observe silently |
| degrading | inject gentle `additionalContext` |
| critical | inject stronger context and notify user |
| handoff_pending | prepare handoff |
| handed_off | silent |

</div>

## Cooldown

Warnings for `degrading` and `critical` states are cooldown-protected so Pilot does not spam repeated interventions.

```text
cooldown_active = current_turn - last_warning_turn < warning_cooldown_turns
```

Cooldown does not suppress manual or forced handoff.

## Stop hook behavior

If the Stop hook sees a critical state, the decision engine returns `prepare_handoff`. This matches the product rule that critical sessions should be summarized before quality drops further.

## Design notes

- The module is pure and side-effect free.
- It does not write to storage.
- It does not generate handoff markdown.
- It only returns a serialisable decision result.
- Hooks and CLI can consume the same decision summary later.
