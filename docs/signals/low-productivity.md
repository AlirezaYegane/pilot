# Low Productivity Signal

`low_productivity` detects when a coding-agent session spends many tokens but changes very few lines compared with a previous-session baseline.

## Why it matters

A session can look active while making little real progress. The agent may keep reading files,
retrying small edits, or explaining itself without producing useful code changes.

This signal is intentionally conservative because some valid tasks are research-heavy.
It should become more meaningful when combined with repeated calls, error cascade, token burn, or backtracking.

## Default policy

```text
productivity = lines_changed / tokens_spent
baseline = previous session average productivity
threshold = current_productivity / baseline_productivity < 0.50
```

## Supported input shapes

- `lines_changed` + `total_tokens`
- `lines_added` / `lines_deleted` + `input_tokens` / `output_tokens`
- `insertions` / `deletions` + `input_tokens_est` / `output_tokens_est`
- explicit `baseline_lines_per_token` for future DB/session summaries

## Score calibration

```text
ratio >= 0.50        -> score = 0.0
0.375 <= ratio < .50 -> score = 0.4
0.25 <= ratio < .375 -> score = 0.7
ratio < 0.25         -> score = 0.95
```

## Examples

<div dir="ltr">

| Current lines/1k tokens | Baseline lines/1k tokens | Ratio | Score | Fired |
|---:|---:|---:|---:|---|
| 10.0 | 10.0 | 1.00 | 0.00 | No |
| 5.0 | 10.0 | 0.50 | 0.00 | No, equal to threshold |
| 3.0 | 10.0 | 0.30 | 0.70 | Yes |
| 1.0 | 10.0 | 0.10 | 0.95 | Yes |

</div>

## Design notes

- This signal should usually start in shadow mode.
- Low productivity alone does not prove degradation.
- It is strongest when combined with token burn, repeated calls, or backtracking.
- The implementation is pure and replay-friendly.
- Future DB integration can pass previous-session baseline stats directly.
