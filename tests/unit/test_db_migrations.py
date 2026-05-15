from __future__ import annotations

from pathlib import Path

from pilot_core.db_migrations import (
    INITIAL_MIGRATION_ID,
    SCHEMA_VERSION,
    applied_migrations,
    bootstrap_database,
    database_health,
    get_busy_timeout_ms,
    get_user_version,
    load_initial_schema_statements,
    open_bootstrapped_connection,
)


def table_exists(db_path: Path, table_name: str) -> bool:
    connection = open_bootstrapped_connection(db_path)
    try:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?;",
            (table_name,),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def test_load_initial_schema_statements_finds_day8_day9_schema() -> None:
    statements = load_initial_schema_statements()

    joined = "\n".join(statements).lower()

    assert "create table" in joined
    assert "sessions" in joined
    assert "turns" in joined
    assert "tool_uses" in joined
    assert "signals" in joined
    assert "alerts" in joined
    assert "create index" in joined


def test_bootstrap_database_creates_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    result = bootstrap_database(db_path)

    assert result.db_path == db_path
    assert result.db_path.exists()
    assert result.user_version == SCHEMA_VERSION
    assert INITIAL_MIGRATION_ID in result.applied_migrations

    expected_tables = {
        "schema_migrations",
        "sessions",
        "turns",
        "tool_uses",
        "signals",
        "alerts",
    }

    for table_name in expected_tables:
        assert table_exists(db_path, table_name)


def test_bootstrap_database_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    first = bootstrap_database(db_path)
    second = bootstrap_database(db_path)

    assert first.applied_migrations == (INITIAL_MIGRATION_ID,)
    assert second.applied_migrations == (INITIAL_MIGRATION_ID,)

    connection = open_bootstrapped_connection(db_path)
    try:
        rows = connection.execute("SELECT id FROM schema_migrations;").fetchall()
        assert [row["id"] for row in rows] == [INITIAL_MIGRATION_ID]
    finally:
        connection.close()


def test_bootstrap_enables_wal_busy_timeout_and_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    result = bootstrap_database(db_path)

    assert result.journal_mode == "wal"
    assert result.busy_timeout_ms >= 5_000
    assert result.foreign_keys_enabled is True

    connection = open_bootstrapped_connection(db_path)
    try:
        assert get_busy_timeout_ms(connection) >= 5_000
        assert get_user_version(connection) == SCHEMA_VERSION
    finally:
        connection.close()


def test_applied_migrations_returns_stable_tuple(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    connection = open_bootstrapped_connection(db_path)

    try:
        assert applied_migrations(connection) == (INITIAL_MIGRATION_ID,)
    finally:
        connection.close()


def test_database_health_is_serialisable(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    health = database_health(db_path)

    assert health["db_path"] == str(db_path)
    assert health["journal_mode"] == "wal"
    assert health["busy_timeout_ms"] >= 5_000
    assert health["foreign_keys_enabled"] is True
    assert health["user_version"] == SCHEMA_VERSION
    assert health["applied_migrations"] == [INITIAL_MIGRATION_ID]


def test_open_bootstrapped_connection_can_read_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    connection = open_bootstrapped_connection(db_path)

    try:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sessions';"
        ).fetchone()
        assert row is not None
        assert row["name"] == "sessions"
    finally:
        connection.close()
