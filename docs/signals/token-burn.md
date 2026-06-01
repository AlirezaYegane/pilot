# Token Burn Signal

`token_burn` detects unusually high recent token usage compared with a prior baseline window.

## Why it matters

A coding-agent session can start burning context and quota quickly when it enters a bad loop,
prints huge outputs, repeatedly inspects large files, or keeps retrying expensive actions.

This signal gives Pilot an early warning before the user hits rate limits or context pressure.

## Default policy

```text
recent_window = latest 3 turns
baseline_window = previous 10 turns
minimum_recent_turns = 2
minimum_baseline_turns = 3
threshold = recent_average_tokens / baseline_average_tokens > 2.0
```

## Score calibration

```text
ratio < 1.5        -> score = 0.0
1.5 <= ratio < 2.0 -> score = 0.4
2.0 <= ratio < 3.0 -> score = 0.7
ratio >= 3.0       -> score = 0.95
```

## Examples

<div dir="ltr">

| Baseline avg | Recent avg | Ratio | Score | Fired |
|---:|---:|---:|---:|---|
| 100 | 100 | 1.00 | 0.00 | No |
| 100 | 180 | 1.80 | 0.40 | No |
| 100 | 250 | 2.50 | 0.70 | Yes |
| 100 | 350 | 3.50 | 0.95 | Yes |

</div>

## Design notes

- The recent window is compared against the previous baseline window, not against itself.
- The signal waits for enough evidence before firing.
- Zero-baseline cases are handled safely.
- The implementation is pure and can be reused by replay tests later.
- This signal should usually start in shadow mode until thresholds are tuned.
