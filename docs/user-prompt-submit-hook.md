# UserPromptSubmit Hook

Day 17 implements turn tracking for the `UserPromptSubmit` Claude Code hook.

## Purpose

When a user submits a prompt, Pilot records a new turn.

The hook:

- reads the JSON payload from stdin
- extracts `session_id`, `cwd`, and `prompt`
- inserts a new row into `turns`
- assigns the next `turn_index`
- stores a compact prompt preview
- resets `tool_count` and `error_count` to zero
- exits with code 0 even if Pilot fails internally

## Why this hook matters

Later hooks such as `PostToolUse` and `PostToolUseFailure` need a current turn
to attach tool calls, token estimates, and error counters to.

## Safety rules

- Do not block prompts in this hook.
- Do not print noisy stdout.
- Do not run heavy signal detection here.
- Log internal errors to Pilot debug log and exit 0.
- Keep timeout low.

## Smoke payload

```json
{
  "session_id": "demo-session",
  "transcript_path": "D:/tmp/transcript.jsonl",
  "cwd": "D:/pilot/pilot",
  "permission_mode": "default",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Build the next feature"
}
