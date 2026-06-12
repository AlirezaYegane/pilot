# Action Policy

Day 41 applies Pilot activation modes to decision-engine results.

## Purpose

The decision engine decides what should happen. The warning renderer formats the output. The action policy decides whether that output is allowed under the configured activation mode.

## Activation modes

<div dir="ltr">

| Mode | Behavior |
|---|---|
| `shadow` | Compute internally but surface nothing. No `additionalContext`, no stderr, no handoff. |
| `warn` | Allow warnings and Claude-facing context, but suppress handoff preparation. |
| `action` | Allow the full decision, including handoff preparation. |

</div>

## Policy order

```text
decision_engine -> action_policy -> warning_renderer -> hook stdout/stderr
```

## Strongest signal wins

When multiple fired signals have different activation modes, the strongest mode wins:

```text
shadow < warn < action
```

For example, if `error_cascade` is warn but `rate_limit` is action, the effective mode is action.

## Why this matters

- New signals can run safely in shadow mode first.
- Users can receive warnings before Pilot performs stronger interventions.
- Handoff preparation only happens when action mode allows it.
- Hook output stays predictable and testable.

## Day 41 files

- `pilot_core/action_policy.py`
- `tests/unit/test_action_policy.py`
- `tests/integration/test_day41_action_policy_replay.py`
- `scripts/smoke_day41_action_policy.py`
