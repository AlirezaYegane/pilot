# SQLite Schema

Pilot uses SQLite as the local-first storage layer.

## Current schema scope

Day 8 introduced:

- schema_migrations
- sessions
- turns

Day 9 adds:

- tool_uses
- signals
- alerts

## Tables

### schema_migrations

Stores applied schema migration versions. Full migration execution will be implemented on Day 10.

### sessions

Stores one monitored Claude Code session.

### turns

Stores user turn boundaries and lightweight per-turn counters.

### tool_uses

Stores tool events observed by hooks.

Important fields:

- session_id
- turn_index
- timestamp_ms
- tool_name
- input_hash
- success
- duration_ms
- input_tokens_est
- output_tokens_est

This table is the future source for repeated-call detection, token burn, error cascade, and productivity signals.

### signals

Stores signal evaluation events.

Important fields:

- session_id
- turn_index
- timestamp_ms
- signal_type
- score
- confidence
- health_score
- state_before
- state_after
- explanation

This table gives the decision engine a history of what degraded and when.

### alerts

Stores Claude-facing or user-facing warnings/actions produced by Pilot.

Important fields:

- alert_type
- severity
- message
- signal_type
- health_score
- state
- delivered_to

This table is separate from signals, because not every signal should produce an alert. Shadow-mode signals are recorded without necessarily alerting.

## Indexes

The schema includes indexes for:

- turns(session_id, turn_index)
- tool_uses(session_id, timestamp_ms)
- tool_uses(session_id, input_hash)
- tool_uses(session_id, turn_index)
- signals(session_id, timestamp_ms)
- signals(session_id, signal_type)
- alerts(session_id, timestamp_ms)
- alerts(session_id, severity)

## Not included yet

Day 10 will add:

- migrations
- DB bootstrap
- WAL mode
- busy timeout
