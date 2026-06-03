# Self-Doubt Signal

`self_doubt` detects repeated assistant uncertainty or repair-loop phrases.

## Why it matters

A coding-agent session often starts degrading when it repeatedly says things like
“let me try again”, “I see the issue now”, or “I was wrong”.

One phrase alone is normal. Three or more markers in a short window can mean the
agent is looping, patching blindly, or losing confidence.

## Default policy

```text
window_size = 8 recent assistant messages
minimum_assistant_messages = 1
threshold = marker_count >= 3
```

## Detection model

- Input is assistant message text from replay or hook records.
- Common shapes such as `text`, `content`, `response`, and `tool_response` are supported.
- Regex matching is case-insensitive.
- The signal is intentionally conservative and starts as a pure detector.

## Examples

<div dir="ltr">

| Pattern | Marker count | Score | Fired |
|---|---:|---:|---|
| Normal implementation notes | 0 | 0.00 | No |
| One “let me try again” | 1 | 0.40 | No |
| Three self-doubt phrases | 3 | 0.70 | Yes |
| Four or more markers | 4+ | 0.95 | Yes |

</div>

## Design notes

- This is not a sentiment detector.
- It only counts known repair-loop phrases.
- The result includes matched phrases for debugging and future tuning.
- The implementation is pure and replay-friendly.
