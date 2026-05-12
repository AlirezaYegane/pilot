# Runtime Paths and Safety

Day 5 introduces the runtime foundation used by future storage and hook code.

## Runtime paths

Path resolution lives in:

```text
pilot_core/paths.py

Pilot resolves:

data_dir
handoff_dir
temp_dir
debug_log_path
db_path

Default local paths follow the project principle of local-first storage:

~/.claude/plugins/pilot/data
~/.claude/plugins/pilot/debug.log
Safety helpers

Fail-silent behaviour lives in:

pilot_core/safety.py

Hook code should use:

run_safely(...)
fail_silent(...)
log_exception(...)
write_debug_log(...)
Rules
Runtime paths must be created through ensure_runtime_dirs.
Hook errors must be logged locally and swallowed.
Debug logging must never raise.
Temp files belong under Pilot's local data directory.
No cloud path or network dependency is allowed in core runtime code.
Why this matters

Pilot is installed inside a user's coding-agent workflow. A Pilot failure must not
become a user-facing Claude Code failure. It is better for Pilot to quietly skip
work than to break the active session.
