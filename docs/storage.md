# Storage Repository API

Day 11 adds the first real repository layer over Pilot's SQLite database.

## Scope

This day covers:

- `SessionRepository`
- `TurnRepository`
- `PilotStorage`
- short-lived storage context helpers

Tool-use and signal repositories are intentionally left for the next day.

## Why this layer exists

Hooks should not scatter raw SQL across the codebase.

Instead of this:

~~~python
connection.execute("UPDATE sessions SET state = ? WHERE id = ?", ...)
~~~

Future hook code should use:

~~~python
storage.sessions.update_state(session_id, state)
storage.turns.increment_tool_count(session_id=session_id, turn_index=turn_index)
~~~

## SessionRepository

Main operations:

- create session
- get / require session
- list recent sessions
- update state
- end session
- add token usage
- set handoff summary path

## TurnRepository

Main operations:

- start turn
- get / require turn
- latest turn
- next turn index
- end turn
- increment tool count
- increment error count
- list turns for a session

## Runtime behavior

The repository opens SQLite with:

- foreign keys enabled
- WAL mode enabled
- busy timeout configured

The schema creation inside `storage.py` is defensive and idempotent. The migration
layer remains the canonical owner of schema evolution.
