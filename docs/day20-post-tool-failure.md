# Day 20: PostToolUseFailure Hook

Day 20 implements failure recording for Claude Code tool calls.

## Goal

When a tool fails, Pilot should record enough information to support future
error-cascade detection without breaking the active Claude Code session.

## Files

- pilot_core/post_tool_failure.py
- hooks/post_tool_failure.py
- tests/unit/test_post_tool_failure.py

## Behaviour

The hook:

- reads JSON payload from stdin
- normalizes common payload shapes
- records a failed tool_use row with success = 0
- stores input hash for future repeat/error analysis
- increments the active turn error counter when possible
- exits 0 even if something goes wrong

## Why this matters

The future error_cascade signal needs recent success/failure history. This hook
creates that evidence trail.
