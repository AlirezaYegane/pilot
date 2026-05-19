# Day 19: PostToolUse Capture

Day 19 implements the successful tool-use capture path.

Scope:
- Read PostToolUse payloads.
- Estimate input and output tokens.
- Record a successful tool_uses row.
- Increment current turn tool_count when possible.
- Update session token totals when possible.
- Never break the user session.

Out of scope today:
- Signal engine evaluation.
- Warning injection.
- Handoff triggering.

Those start in the Signal Engine and Decision Engine milestones.

Runtime rules:
- Hook exits with status code 0 even on internal errors.
- Normal success prints nothing to stdout.
- Debug information goes to the local Pilot debug log.
- SQLite writes use busy_timeout and foreign key checks.

Files:
- hooks/post_tool_use.py
- pilot_core/post_tool_use.py
- pilot_core/token_estimation.py
- tests/unit/test_post_tool_use.py
