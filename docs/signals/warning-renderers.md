# Warning Renderers

Day 40 adds the formatting layer between Pilot decisions and hook-safe output.

## Purpose

The decision engine decides what should happen. The warning renderer decides how that decision is shown to Claude Code or to the user.

## Outputs

<div dir="ltr">

| Renderer | Output | Used by |
|---|---|---|
| `render_claude_additional_context()` | string or `None` | Claude-facing `additionalContext` |
| `render_user_stderr()` | string or `None` | user-facing terminal warning |
| `render_hook_stdout_payload()` | dict | hook stdout JSON payload |
| `warning_summary()` | dict | smoke tests and future CLI |

</div>

## Hook stdout contract

```json
{
  "additionalContext": "Pilot context: session degrading..."
}
```

Safe decisions return an empty payload:

```json
{}
```

## Design rules

- The module is pure and side-effect free.
- It does not print to stderr directly.
- It does not write to storage.
- It does not decide policy.
- It only renders `DecisionResult` into bounded text.

## State behavior

<div dir="ltr">

| State | Claude additionalContext | User stderr |
|---|---|---|
| healthy | no | no |
| watching | no | no |
| degrading | yes | usually no |
| critical | yes | yes |
| handoff_pending | yes | yes |
| handed_off | no | no |

</div>

## Why this is separate from Day 41

Day 40 only formats warnings. Day 41 will own action policy: which states only warn, which states prepare handoff, and how activation modes affect behavior.
