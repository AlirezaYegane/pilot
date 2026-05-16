# Day 13: Storage Contract Tests

Day 13 hardens the SQLite storage foundation.

## Scope

- Verify core storage tables exist
- Verify SQLite WAL and busy timeout are supported
- Verify insert/select/update roundtrips
- Verify multi-session isolation
- Catch type-conversion regressions around SQLite nullable values

## Why this matters

Pilot depends on a reliable local SQLite database. Later hook and signal logic will
write session, turn, tool-use, and signal events frequently. If this layer is not
stable, downstream signal detection and handoff generation will be unreliable.

## Tested contracts

- `sessions` can be inserted, selected, and updated
- `turns` are scoped by `session_id`
- `tool_uses` are scoped by `session_id`
- `signals` are scoped by `session_id`
- WAL mode and busy timeout can be enabled
- Multiple sessions do not bleed rows into each other

## Quality gate

```powershell
ruff format .
ruff check . --fix
mypy pilot_core tests
pytest
pre-commit run --all-files
