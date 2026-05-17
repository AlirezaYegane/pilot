# Day 14 Storage Hot-Path Benchmark

## Summary

- Schema v1 check: **PASS**
- Locking probe: **PASS**
- DB path: `artifacts\day14\day14_storage_benchmark.db`

## Hot-path timings

| Operation | Count | p50 ms | p95 ms | Max ms |
|---|---:|---:|---:|---:|
| insert_turn | 250 | 1.2234 | 1.4375 | 4.4003 |
| insert_tool_use | 250 | 1.2216 | 1.4187 | 2.6745 |
| select_recent_tool_uses | 250 | 0.0337 | 0.0457 | 0.0757 |
| update_session_state | 250 | 1.1816 | 1.3886 | 1.5494 |

## Locking probe

| Writers | Events / writer | Expected events | Actual events | Errors |
|---:|---:|---:|---:|---:|
| 4 | 50 | 200 | 200 | 0 |

## Schema v1 tables

- `alerts`
- `schema_migrations`
- `sessions`
- `signals`
- `tool_uses`
- `turns`

## Schema v1 indexes

- `idx_alerts_session`
- `idx_alerts_severity`
- `idx_sessions_parent`
- `idx_sessions_started_at`
- `idx_sessions_state`
- `idx_signals_session`
- `idx_signals_type`
- `idx_tool_uses_hash`
- `idx_tool_uses_session`
- `idx_turns_session`

## Interpretation

Day 14 does not claim production performance yet. It creates a repeatable baseline
for local SQLite hot paths before hook plumbing begins in Week 3.

The important checks are:

- schema v1 surface exists
- WAL/busy-timeout concurrent writes complete without lock errors
- insert/select/update operations have a measured baseline
- results are saved as reproducible evidence
