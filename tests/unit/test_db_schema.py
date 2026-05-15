from __future__ import annotations

import sqlite3

import pytest

from pilot_core.constants import SessionState
from pilot_core.db_schema import (
    SCHEMA_VERSION,
    TABLES,
    create_schema_sql,
    expected_columns,
    schema_summary,
    schema_table_names,
)


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table';").fetchall()
    return {str(row[0]) for row in rows}


def _column_names(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    rows = connection.execute(f"PRAGMA table_info({table_name});").fetchall()
    return tuple(str(row[1]) for row in rows)


def test_schema_version_is_first_storage_version() -> None:
    assert SCHEMA_VERSION == 1


def test_schema_declares_tables_in_creation_order() -> None:
    assert schema_table_names() == ("schema_migrations", "sessions", "turns")
    assert tuple(table.name for table in TABLES) == schema_table_names()


def test_schema_summary_is_serialisable() -> None:
    assert schema_summary() == {
        "schema_version": 1,
        "tables": ("schema_migrations", "sessions", "turns"),
    }


def test_expected_columns_for_known_tables() -> None:
    assert expected_columns("sessions") == (
        "id",
        "started_at",
        "ended_at",
        "cwd",
        "model",
        "parent_session_id",
        "total_input_tokens",
        "total_output_tokens",
        "estimated_cost_usd",
        "state",
        "handoff_summary_path",
        "created_at",
        "updated_at",
    )

    assert expected_columns("turns") == (
        "id",
        "session_id",
        "turn_index",
        "started_at",
        "ended_at",
        "user_prompt_preview",
        "tool_count",
        "error_count",
        "created_at",
        "updated_at",
    )


def test_expected_columns_rejects_unknown_table() -> None:
    with pytest.raises(ValueError, match="Unknown schema table"):
        expected_columns("missing")


def test_create_schema_sql_bootstraps_day8_tables() -> None:
    connection = _connect()

    connection.executescript(create_schema_sql())

    names = _table_names(connection)
    assert "schema_migrations" in names
    assert "sessions" in names
    assert "turns" in names


def test_sessions_table_has_expected_columns() -> None:
    connection = _connect()
    connection.executescript(create_schema_sql())

    assert _column_names(connection, "sessions") == expected_columns("sessions")


def test_turns_table_has_expected_columns() -> None:
    connection = _connect()
    connection.executescript(create_schema_sql())

    assert _column_names(connection, "turns") == expected_columns("turns")


def test_session_defaults_are_applied() -> None:
    connection = _connect()
    connection.executescript(create_schema_sql())

    connection.execute(
        """
        INSERT INTO sessions (id, started_at, cwd, model, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        ("session-1", 1_000, "D:/pilot/pilot", "claude-sonnet", 1_000, 1_000),
    )

    row = connection.execute(
        """
        SELECT
            total_input_tokens,
            total_output_tokens,
            estimated_cost_usd,
            state,
            handoff_summary_path
        FROM sessions
        WHERE id = ?;
        """,
        ("session-1",),
    ).fetchone()

    assert row == (0, 0, 0.0, SessionState.HEALTHY.value, None)


def test_sessions_table_rejects_unknown_state() -> None:
    connection = _connect()
    connection.executescript(create_schema_sql())

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO sessions (
                id,
                started_at,
                state,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?);
            """,
            ("session-1", 1_000, "broken", 1_000, 1_000),
        )


def test_turns_table_links_to_sessions() -> None:
    connection = _connect()
    connection.executescript(create_schema_sql())

    connection.execute(
        """
        INSERT INTO sessions (id, started_at, created_at, updated_at)
        VALUES (?, ?, ?, ?);
        """,
        ("session-1", 1_000, 1_000, 1_000),
    )

    connection.execute(
        """
        INSERT INTO turns (
            session_id,
            turn_index,
            started_at,
            user_prompt_preview,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        ("session-1", 0, 1_001, "hello", 1_001, 1_001),
    )

    row = connection.execute(
        """
        SELECT session_id, turn_index, tool_count, error_count
        FROM turns
        WHERE session_id = ?;
        """,
        ("session-1",),
    ).fetchone()

    assert row == ("session-1", 0, 0, 0)


def test_turns_table_rejects_missing_session() -> None:
    connection = _connect()
    connection.executescript(create_schema_sql())

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO turns (
                session_id,
                turn_index,
                started_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?);
            """,
            ("missing-session", 0, 1_001, 1_001, 1_001),
        )


def test_turns_table_rejects_duplicate_turn_index_per_session() -> None:
    connection = _connect()
    connection.executescript(create_schema_sql())

    connection.execute(
        """
        INSERT INTO sessions (id, started_at, created_at, updated_at)
        VALUES (?, ?, ?, ?);
        """,
        ("session-1", 1_000, 1_000, 1_000),
    )

    payload = ("session-1", 0, 1_001, 1_001, 1_001)

    connection.execute(
        """
        INSERT INTO turns (
            session_id,
            turn_index,
            started_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?);
        """,
        payload,
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO turns (
                session_id,
                turn_index,
                started_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?);
            """,
            payload,
        )


def test_day8_indexes_are_created() -> None:
    connection = _connect()
    connection.executescript(create_schema_sql())

    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'index';").fetchall()
    index_names = {str(row[0]) for row in rows}

    assert "idx_sessions_started_at" in index_names
    assert "idx_sessions_state" in index_names
    assert "idx_sessions_parent" in index_names
    assert "idx_turns_session" in index_names
    assert "idx_turns_started_at" in index_names
