# Storage Repositories

Day 12 adds repository helpers for tool-use and signal-event records.

## Why this exists

The next phase of Pilot is hook plumbing. Hook handlers need a small, stable API for writing operational events into SQLite without duplicating SQL in every hook file.

## Added APIs

```text
storage_transaction(...)
ToolUseRepository
SignalEventRepository
get_storage_repositories(...)
record_tool_use(...)
record_signal_event(...)
Tool-use records

Tool-use rows support:

session_id
turn_index
timestamp_ms
tool_name
input_hash
input_size
output_size
success
duration_ms
input_tokens_est
output_tokens_est

This prepares the project for repeated-call detection, error-cascade detection, token tracking, and low-productivity analysis.

Signal events

Signal-event rows support:

session_id
timestamp_ms
signal_type
score
health_score
state_before
state_after
metadata_json

This prepares the project for the signal engine and state-machine layers.

Transaction rule

Use storage_transaction(...) whenever a hook needs to write more than one related row. On success it commits. On failure it rolls back.

Design rule

Storage helpers should stay boring and predictable. Hooks must be fast, safe, and easy to reason about.
