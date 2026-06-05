# Signal Registry

`signal_registry` is the central registry for Pilot degradation signals.

## Why it matters

After all 8 signals exist, Pilot needs one stable place to decide:

- which signals are registered
- which signals are enabled or disabled
- which activation mode each signal uses
- whether a fired signal should stay shadow-only, warn, or become action-level

Day 33 does not compute final health score yet. That belongs to the upcoming decision layer.

## Registered signals

```text
token_burn
repeated_calls
error_cascade
backtracking
context_saturation
self_doubt
rate_limit
low_productivity
```

## Activation modes

<div dir="ltr">

| Mode | Meaning | Registry outcome |
|---|---|---|
| `shadow` | evaluate only | `fired=True`, but no warning/action |
| `warn` | user/Claude warning eligible | `should_warn=True` |
| `action` | strong policy eligible | `should_warn=True`, `should_action=True` |

</div>

## Dynamic policy

```text
enabled_signals = optional allow-list
disabled_signals = deny-list
activation_overrides = per-signal shadow/warn/action map
default_activation = fallback mode
```

## Design notes

- Disabled signals are not evaluated.
- Registry evaluation normalises score, confidence, severity, fired, and explanation.
- The registry does not decide health score.
- The registry is intentionally immutable: policy changes return a new registry.
- This keeps future hook integration safer and easier to test.
