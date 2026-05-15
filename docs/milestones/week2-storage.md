# Milestone: Week 2 — Storage Layer

## Goal

Build Pilot's local SQLite foundation.

Pilot needs a reliable local database before hooks and signal detection can become real. Week 2 creates that database layer while preserving the project rules:

- local-first
- fail-safe
- testable
- migration-friendly
- safe for concurrent Claude Code sessions

## Scope

### Day 8

- Define SQLite schema v1
- Add `sessions` table
- Add `turns` table
- Add schema docs

### Day 9

- Add `tool_uses` table
- Add `signals` table
- Add `alerts` table
- Add indexes

### Day 10

- Add migration system
- Add database bootstrap
- Enable WAL mode
- Set SQLite busy timeout

### Day 11

- Implement `storage.py`
- Add session repository API
- Add turn repository API

### Day 12

- Add tool-use repository API
- Add signal-event repository API
- Add transaction wrapper

### Day 13

- Add DB tests
- Insert/select/update tests
- Multi-session tests
- Migration idempotency tests

### Day 14

- Benchmark local DB hot paths
- Verify no locking surprises
- Finalize schema v1

## Non-goals

- No signal detection yet
- No hook integration yet
- No handoff generation yet
- No CLI UI polish yet

## Acceptance criteria

- Database can be created from scratch.
- Migrations can run more than once safely.
- WAL mode is enabled.
- Busy timeout is configured.
- Session rows can be inserted and updated.
- Turn rows can be inserted and updated.
- Tool-use rows can be inserted and queried.
- Signal rows can be inserted and queried.
- Tests do not touch the real user data directory.
- `ruff`, `mypy`, `pytest`, and `pre-commit` are green.
