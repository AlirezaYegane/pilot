# Rate Limit Signal

`rate_limit` detects whether the current token burn trajectory is likely to exhaust the user plan quota soon.

## Why it matters

When a coding-agent session starts burning tokens rapidly, the user may hit a quota or rate limit before the task is complete.

This signal gives Pilot an early warning so the session can slow down, summarize progress, or prepare a handoff before tokens are wasted.

## Default policy

```text
plan = max5
plan_cap_tokens = 250,000,000
recent_rate_window_minutes = 5
minimum_recent_events = 2
eta_threshold_minutes = 20
fire when eta_minutes < 20
```

## Score calibration

```text
eta <= 0 min      -> score = 1.00
eta < 10 min      -> score = 1.00
eta < 20 min      -> score = 0.85
eta < 40 min      -> score = 0.50
eta unknown/far   -> score = 0.00
```

## Supported plan caps

<div dir="ltr">

| Plan | Weekly token cap |
|---|---:|
| pro | 50,000,000 |
| max5 | 250,000,000 |
| max20 | 1,000,000,000 |

</div>

## Design notes

- The signal is pure and does not read account data directly.
- The caller can pass explicit current usage and explicit plan cap.
- Unknown plans fall back to the default `max5` cap.
- ETA is only computed from timestamped events.
- Missing or sparse data returns a low-confidence non-firing result.
