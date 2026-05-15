"""SQLite bootstrap and migration helpers for Pilot.

Day 10 goal:
- create the database automatically
- apply schema migrations idempotently
- enable WAL for safer concurrent access
- set busy_timeout to reduce lock-related flakiness

This module intentionally does not implement repository CRUD methods yet.
That belongs to Day 11/12.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pilot_core.paths import RuntimePaths, ensure_runtime_dirs, resolve_runtime_paths

SCHEMA_VERSION = 1
INITIAL_MIGRATION_ID = "001_initial_schema"
BUSY_TIMEOUT_MS = 5_000


@dataclass(frozen=True)
class DatabaseBootstrapResult:
    """Result returned after database bootstrap."""

    db_path: Path
    journal_mode: str
    busy_timeout_ms: int
    foreign_keys_enabled: bool
    user_version: int
    applied_migrations: tuple[str, ...]


def connect_sqlite(db_path: str | Path, *, timeout_seconds: float = 5.0) -> sqlite3.Connection:
    """Open a SQLite connection with Pilot's runtime defaults."""

    connection = sqlite3.connect(str(db_path), timeout=timeout_seconds)
    connection.row_factory = sqlite3.Row
    configure_connection(connection)
    return connection


def configure_connection(connection: sqlite3.Connection) -> None:
    """Configure per-connection SQLite safety settings."""

    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};")


def enable_wal(connection: sqlite3.Connection) -> str:
    """Enable WAL journal mode and return the effective journal mode.

    SQLite may return a different value for unsupported database types. For
    normal file-backed Pilot databases, this should be "wal".
    """

    row = connection.execute("PRAGMA journal_mode = WAL;").fetchone()
    if row is None:
        return ""
    return str(row[0]).lower()


def ensure_schema_migrations_table(connection: sqlite3.Connection) -> None:
    """Create the internal migration tracking table."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );
        """
    )


def applied_migrations(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Return applied migration ids in stable order."""

    rows = connection.execute(
        "SELECT id FROM schema_migrations ORDER BY applied_at, id;"
    ).fetchall()
    return tuple(str(row["id"]) for row in rows)


def get_user_version(connection: sqlite3.Connection) -> int:
    """Return SQLite PRAGMA user_version."""

    row = connection.execute("PRAGMA user_version;").fetchone()
    if row is None:
        return 0
    return int(row[0])


def get_busy_timeout_ms(connection: sqlite3.Connection) -> int:
    """Return SQLite PRAGMA busy_timeout."""

    row = connection.execute("PRAGMA busy_timeout;").fetchone()
    if row is None:
        return 0
    return int(row[0])


def foreign_keys_enabled(connection: sqlite3.Connection) -> bool:
    """Return whether foreign key enforcement is enabled."""

    row = connection.execute("PRAGMA foreign_keys;").fetchone()
    if row is None:
        return False
    return int(row[0]) == 1


def _normalise_sql_statements(value: object) -> tuple[str, ...]:
    """Convert a schema export into a clean tuple of SQL statements."""

    statements: tuple[str, ...]

    if isinstance(value, str):
        statements = (value,)
    elif isinstance(value, Iterable):
        statements = tuple(item for item in value if isinstance(item, str))
    else:
        return ()

    return tuple(statement.strip() for statement in statements if statement.strip())


def _is_create_statement(statement: str) -> bool:
    """Return True for schema statements we can safely execute as migration SQL."""

    upper = statement.lstrip().upper()
    return upper.startswith("CREATE TABLE") or upper.startswith("CREATE INDEX")


def _dedupe_statements(statements: Sequence[str]) -> tuple[str, ...]:
    """Deduplicate SQL statements while preserving order."""

    seen: set[str] = set()
    deduped: list[str] = []

    for statement in statements:
        key = " ".join(statement.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(statement)

    return tuple(deduped)


def load_initial_schema_statements() -> tuple[str, ...]:
    """Load Day 8/9 schema SQL from pilot_core.db_schema.

    The previous days may have used slightly different export names while we
    were evolving the schema. This loader first checks canonical names, then
    falls back to safe introspection of CREATE TABLE / CREATE INDEX statements.
    """

    from pilot_core import db_schema

    all_in_one_names = (
        "ALL_SCHEMA_STATEMENTS",
        "SCHEMA_STATEMENTS",
        "CREATE_SCHEMA_STATEMENTS",
    )

    for name in all_in_one_names:
        value = getattr(db_schema, name, None)
        statements = _normalise_sql_statements(value)
        if statements:
            return _dedupe_statements(statements)

    ordered_group_names = (
        "CREATE_TABLE_STATEMENTS",
        "TABLE_STATEMENTS",
        "BASE_TABLE_STATEMENTS",
        "CREATE_INDEX_STATEMENTS",
        "INDEX_STATEMENTS",
    )

    grouped_statements: list[str] = []
    for name in ordered_group_names:
        grouped_statements.extend(_normalise_sql_statements(getattr(db_schema, name, None)))

    if grouped_statements:
        return _dedupe_statements(grouped_statements)

    discovered: list[tuple[str, str]] = []
    for name in dir(db_schema):
        if name.startswith("_"):
            continue
        for statement in _normalise_sql_statements(getattr(db_schema, name, None)):
            if _is_create_statement(statement):
                discovered.append((name, statement))

    discovered.sort(key=lambda item: item[0])
    discovered_statements = [statement for _, statement in discovered]

    if not discovered_statements:
        msg = (
            "No schema statements found in pilot_core.db_schema. "
            "Expected SCHEMA_STATEMENTS, CREATE_TABLE_STATEMENTS, or CREATE INDEX/TABLE SQL exports."
        )
        raise RuntimeError(msg)

    return _dedupe_statements(discovered_statements)


def apply_initial_schema_migration(connection: sqlite3.Connection) -> bool:
    """Apply the initial schema migration if it has not already run.

    Returns True when the migration was newly applied, False when it was already
    present.
    """

    ensure_schema_migrations_table(connection)

    already_applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE id = ?;",
        (INITIAL_MIGRATION_ID,),
    ).fetchone()

    if already_applied is not None:
        return False

    statements = load_initial_schema_statements()

    with connection:
        for statement in statements:
            connection.execute(statement)

        connection.execute(
            "INSERT INTO schema_migrations (id) VALUES (?);",
            (INITIAL_MIGRATION_ID,),
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")

    return True


def bootstrap_database(
    db_path: str | Path | None = None,
    *,
    paths: RuntimePaths | None = None,
) -> DatabaseBootstrapResult:
    """Create and migrate the Pilot SQLite database."""

    resolved_paths = ensure_runtime_dirs(paths or resolve_runtime_paths())
    final_db_path = Path(db_path) if db_path is not None else resolved_paths.db_path
    final_db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = connect_sqlite(final_db_path)
    try:
        journal_mode = enable_wal(connection)
        apply_initial_schema_migration(connection)

        return DatabaseBootstrapResult(
            db_path=final_db_path,
            journal_mode=journal_mode,
            busy_timeout_ms=get_busy_timeout_ms(connection),
            foreign_keys_enabled=foreign_keys_enabled(connection),
            user_version=get_user_version(connection),
            applied_migrations=applied_migrations(connection),
        )
    finally:
        connection.close()


def open_bootstrapped_connection(
    db_path: str | Path | None = None,
    *,
    paths: RuntimePaths | None = None,
) -> sqlite3.Connection:
    """Bootstrap the database and return an open configured connection."""

    result = bootstrap_database(db_path=db_path, paths=paths)
    return connect_sqlite(result.db_path)


def database_health(
    db_path: str | Path | None = None,
    *,
    paths: RuntimePaths | None = None,
) -> dict[str, Any]:
    """Return a small diagnostic snapshot for CLI/doctor use."""

    result = bootstrap_database(db_path=db_path, paths=paths)
    return {
        "db_path": str(result.db_path),
        "journal_mode": result.journal_mode,
        "busy_timeout_ms": result.busy_timeout_ms,
        "foreign_keys_enabled": result.foreign_keys_enabled,
        "user_version": result.user_version,
        "applied_migrations": list(result.applied_migrations),
    }
