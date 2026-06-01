# Error Cascade Signal

`error_cascade` detects repeated tool failures inside a short rolling window.

## Why it matters

A coding-agent session often degrades when it keeps running failing commands,
retrying broken edits, or repeatedly hitting the same runtime error.

This signal gives Pilot an early warning that the session may need correction
before more tokens and time are burned.

## Default policy

```text
window_size = 5 recent tool outcomes
minimum_observations = 3
threshold = failure_rate > 0.40
```

## Score calibration

```text
score = clamp(failure_rate / threshold, 0.0, 1.0)
```

## Examples

<div dir="ltr">

| Recent failures | Failure rate | Score | Fired |
|---:|---:|---:|---|
| 1 / 5 | 0.20 | 0.50 | No |
| 2 / 5 | 0.40 | 1.00 | No, equal to threshold |
| 3 / 5 | 0.60 | 1.00 | Yes |

</div>

## Design notes

- The signal waits for at least 3 observations.
- Only the latest rolling window is evaluated.
- Dict records with `success=false` are failures.
- Dict records with an `error` payload are treated as failures.
- The implementation is pure and can be reused by replay tests later.
