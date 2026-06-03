# Backtracking Signal

`backtracking` detects repeated edits to recently edited files when there has been no user feedback between those edits.

## Why it matters

A coding-agent session often degrades when the model keeps editing the same file again and again without new instructions.
That pattern can mean the agent is stuck, undoing itself, or guessing instead of making forward progress.

## Default policy

```text
lookback_turns = 3
minimum_edit_events = 2
threshold = backtrack_count >= 2
user_feedback_between_edits = suppress backtracking count
```

## Detection model

- Edit events are detected from `Edit`, `MultiEdit`, or `Write` tool calls.
- File identity is based on a normalised file path.
- User feedback events are detected from `user_prompt`, `user_feedback`, or `role=user` records.
- A repeated edit only counts when no user feedback happened between the previous edit and the current edit.

## Examples

<div dir="ltr">

| Pattern | Backtrack count | Score | Fired |
|---|---:|---:|---|
| Edit A, Edit B, Edit C | 0 | 0.00 | No |
| Edit A, Edit A | 1 | 0.40 | No |
| Edit A, Edit A, Edit A | 2 | 0.70 | Yes |
| Edit A, User feedback, Edit A | 0 | 0.00 | No |

</div>

## Design notes

- The signal is pure and replay-friendly.
- It should start in shadow mode until false positives are reviewed.
- It is intentionally conservative: user feedback breaks the backtracking chain.
- This is not a lint signal; it only detects repeated edit behavior.
