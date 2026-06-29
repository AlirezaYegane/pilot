# Day 53 Session CLI

Day 53 adds the session-oriented CLI views:

- pilot sessions
- pilot show <session_id>
- session list renderer
- session detail renderer

## Purpose

Day 52 made pilot status useful for the current health view. Day 53 makes Pilot inspectable across previous sessions.

## Commands

pilot sessions lists recent sessions from the local SQLite database.

pilot show <session_id> renders one session with summary, signals, tool calls, token counts, and handoff path.

## Design

- Rendering lives in pilot_core/render/session_view.py.
- SQLite loading lives in pilot_core/session_cli.py.
- The renderer is pure and does not read the database.
- The DB loader is defensive and returns empty views instead of crashing when a DB/table is missing.
- The existing pilot status command is preserved by wrapping the previous CLI entrypoint.

## Expected behavior

- Missing DB: pilot sessions shows an empty list.
- Missing session id: pilot show returns exit code 1.
- Existing session: pilot show prints summary, signals, tools, and handoff path.

## Quality gate

Day 53 must pass:

- ruff
- mypy
- unit renderer tests
- integration SQLite CLI tests
- smoke script
- full pytest
- pre-commit run --all-files
