# Handoff Markdown Renderer

Day 46 adds the markdown renderer for Pilot handoff summaries.

## Purpose

The renderer converts `HandoffSchema` into concise, deterministic markdown that can later be written by the stop hook or loaded by session-start resume flow.

Day 46 intentionally does not wire the stop hook. Stop-hook integration is Day 47.

## Main API

<div dir="ltr">

| Function / Type | Purpose |
|---|---|
| `render_handoff_markdown()` | Convert a `HandoffSchema` into markdown |
| `HandoffMarkdownOptions` | Configure style, metadata, empty sections, and bounds |
| `HandoffMarkdownStyle` | `compact` or `full` rendering |
| `handoff_markdown_summary()` | Compact serialisable summary for smoke tests and CLI |

</div>

## Output structure

```text
# Pilot Handoff
## Metadata
## Task
## Progress
## Decisions
## Files Modified
## Blockers
## Next Step
## Do Not Redo
## Notes
```

Optional sections are omitted by default when empty. This keeps healthy-session handoffs concise.

## Design rules

- Renderer is pure and side-effect free.
- It does not read SQLite.
- It does not call hooks.
- It does not decide whether handoff should happen.
- It preserves stable section order.
- It bounds long text using `... [truncated]`.
- It supports compact and full style.

## Example

```markdown
# Pilot Handoff

## Task
Continue from replay case: degraded_session

## Progress
Read 16 replay records and extracted 2 blocker(s).

## Blockers
- **error**: Failing loop detected for Bash — same pytest failure

## Next Step
Use this markdown as the next-session handoff context.
```

## Smoke command

```powershell
python scripts\smoke_day46_handoff_markdown.py
```
