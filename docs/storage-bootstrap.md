# Storage Bootstrap and Migrations

Day 10 adds the first real SQLite bootstrap layer.

## Goal

The database should be created automatically and safely every time Pilot needs storage.

This includes:

- creating runtime directories
- opening a configured SQLite connection
- enabling foreign keys
- enabling WAL mode
- setting busy_timeout
- applying schema migrations idempotently
- storing applied migration ids

## Main module

pilot_core/db_migrations.py

## Public entrypoints

bootstrap_database(...)
open_bootstrapped_connection(...)
database_health(...)

pilot_core/storage.py exposes a thin wrapper for now:

get_connection(...)
ensure_database(...)
healthcheck(...)

Repository-level APIs are intentionally deferred to Day 11 and Day 12.

## Migration policy

The first migration is:

001_initial_schema

It uses the schema statements defined in:

pilot_core/db_schema.py

Migrations are tracked in:

schema_migrations

## SQLite runtime settings

Pilot uses these SQLite PRAGMAs:

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA user_version = 1;

## Why WAL matters

Claude Code can run multiple hook subprocesses. Those subprocesses may touch the same local database close together.

WAL mode makes this safer and reduces lock contention for the local-first workflow.

## Day 10 boundary

Day 10 does not implement session, turn, or tool repository CRUD.

That comes next:

- Day 11: session and turn repositories
- Day 12: tool-use and signal repositories
