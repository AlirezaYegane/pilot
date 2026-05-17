# Storage Schema v1

Day 14 freezes the Week 2 SQLite storage surface before hook plumbing begins.

## Why this document exists

Pilot is a local-first Claude Code plugin. Hook code will soon write into SQLite
on every session, turn, tool call, failure, signal, and alert.

Before hooks are connected, the schema needs a stable v1 contract.

## Required tables

| Table | Purpose |
|---|---|
| `schema_migrations` | Tracks applied schema migrations |
| `sessions` | One row per Claude Code session |
| `turns` | One row per user prompt / turn |
| `tool_uses` | One row per successful tool execution |
| `signals` | Signal evaluation events and health transitions |
| `alerts` | User-facing or agent-facing warnings |

## Required index families

| Index prefix | Purpose |
|---|---|
| `idx_sessions_` | Fast session listing/filtering |
| `idx_turns_` | Fast turn lookup per session |
| `idx_tool_uses_` | Fast tool history and repeated-call checks |
| `idx_signals_` | Fast signal history lookup |
| `idx_alerts_` | Fast alert lookup and filtering |

## Runtime requirements

The SQLite runtime must use:

```text
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
Day 14 acceptance criteria
Schema v1 tables are present
Schema v1 indexes are present
WAL-mode concurrent writes complete without lock errors
Hot-path operations have a reproducible benchmark report
Quality gates are green
What is intentionally not frozen yet

The exact final shape of future signal payloads is not frozen in Day 14.
Week 4 will introduce the signal result contract with score, confidence, and explanation.
