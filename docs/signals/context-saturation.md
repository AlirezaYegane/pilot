# Context Saturation Signal

`context_saturation` estimates how close the active session is to the model context limit.

## Why it matters

A coding-agent session can degrade when the context window becomes crowded.
The model may lose earlier details, repeat work, miss constraints, or need a handoff.

Pilot cannot directly read the true Claude Code context window, so it estimates context usage
from cumulative token events plus a conservative system prompt offset.

## Default policy

```text
context_tokens = sum(input_tokens + output_tokens) + system_prompt_token_offset
default_context_limit = 200000
system_prompt_token_offset = 20000
threshold = context_tokens / model_context_limit > 0.80
```

## Model limit abstraction

```text
explicit context limit > known model name > 1M/200k model-name hints > default 200k
```

## Score calibration

```text
ratio < 0.60       -> score = 0.0
0.60 <= ratio < .8 -> score = 0.6
0.80 <= ratio < .9 -> score = 0.8
0.90 <= ratio < 1  -> score = 0.95
ratio >= 1.0       -> score = 1.0
```

## Examples

<div dir="ltr">

| Context tokens | Limit | Ratio | Score | Fired |
|---:|---:|---:|---:|---|
| 70000 | 200000 | 0.35 | 0.00 | No |
| 155000 | 200000 | 0.78 | 0.60 | No |
| 170000 | 200000 | 0.85 | 0.80 | Yes |
| 210000 | 200000 | 1.05 | 1.00 | Yes |

</div>

## Design notes

- This is an estimate, not the real model context size.
- The system prompt offset makes the estimate conservative.
- The signal supports explicit context limits for tests and future config.
- Known 1M-context model names resolve to a larger limit.
- This signal should start in shadow mode until thresholds are tuned.
