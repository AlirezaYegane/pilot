# Storage Schema — Day 8

Day 8 defines the first SQLite schema contract for Pilot.

## Scope

This day covers only:

- schema_migrations
- sessions
- turns

The following are intentionally left for later days:

- tool_uses
- signals
- alerts
- migration runner
- WAL mode
- busy timeout
- repository APIs

## Why schema starts here

Pilot needs a stable local store before hooks can safely collect events. The core runtime principle is local-first storage, so the database lives under Pilot's local data directory.

## Tables

### schema_migrations

Tracks applied schema versions.

### sessions

Stores one monitored Claude Code session.

Important fields:

- id
- started_at
- ended_at
- cwd
- model
- parent_session_id
- total_input_tokens
- total_output_tokens
- estimated_cost_usd
- state
- handoff_summary_path
- created_at
- updated_at

### turns

Stores user-prompt turns inside a session.

Important fields:

- id
- session_id
- turn_index
- started_at
- ended_at
- user_prompt_preview
- tool_count
- error_count
- created_at
- updated_at

## Constraints

- sessions.state must match a known SessionState.
- token counters cannot be negative.
- estimated cost cannot be negative.
- turns.session_id must reference an existing session.
- each session_id and turn_index pair must be unique.

## Next storage days

- Day 9: add tool_uses, signals, and alerts
- Day 10: add migrations, bootstrap, WAL mode, and busy timeout
- Day 11: implement session and turn repository APIs
