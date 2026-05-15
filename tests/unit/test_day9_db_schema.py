from __future__ import annotations

import sqlite3

from pilot_core.db_schema import schema_statements, table_names


def _create_db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON;")
    for statement in schema_statements():
        connection.execute(statement)
    return connection


def test_schema_contains_day9_tables() -> None:
    assert table_names() == ("sessions", "turns", "tool_uses", "signals", "alerts")


def test_schema_executes_cleanly_in_sqlite() -> None:
    connection = _create_db()

    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name;"
    ).fetchall()

    names = {row[0] for row in rows}

    assert "sessions" in names
    assert "turns" in names
    assert "tool_uses" in names
    assert "signals" in names
    assert "alerts" in names


def test_tool_uses_table_has_required_columns() -> None:
    connection = _create_db()

    columns = {row[1] for row in connection.execute("PRAGMA table_info(tool_uses);").fetchall()}

    assert {
        "id",
        "session_id",
        "turn_index",
        "timestamp_ms",
        "tool_name",
        "input_hash",
        "input_size",
        "output_size",
        "success",
        "duration_ms",
        "input_tokens_est",
        "output_tokens_est",
        "input_preview",
        "output_preview",
        "created_at",
    }.issubset(columns)


def test_signals_table_has_required_columns() -> None:
    connection = _create_db()

    columns = {row[1] for row in connection.execute("PRAGMA table_info(signals);").fetchall()}

    assert {
        "id",
        "session_id",
        "turn_index",
        "timestamp_ms",
        "signal_type",
        "score",
        "confidence",
        "health_score",
        "state_before",
        "state_after",
        "explanation",
        "created_at",
    }.issubset(columns)


def test_alerts_table_has_required_columns() -> None:
    connection = _create_db()

    columns = {row[1] for row in connection.execute("PRAGMA table_info(alerts);").fetchall()}

    assert {
        "id",
        "session_id",
        "turn_index",
        "timestamp_ms",
        "alert_type",
        "severity",
        "message",
        "signal_type",
        "health_score",
        "state",
        "delivered_to",
        "created_at",
    }.issubset(columns)


def test_day9_indexes_exist() -> None:
    connection = _create_db()

    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' ORDER BY name;"
    ).fetchall()

    names = {row[0] for row in rows}

    assert "idx_tool_uses_session" in names
    assert "idx_tool_uses_hash" in names
    assert "idx_tool_uses_turn" in names
    assert "idx_signals_session" in names
    assert "idx_signals_type" in names
    assert "idx_alerts_session" in names
    assert "idx_alerts_severity" in names


def test_day9_tables_accept_minimal_valid_rows() -> None:
    connection = _create_db()

    connection.execute(
        """
        INSERT INTO sessions (
            id,
            started_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?);
        """,
        ("session-1", 1000, 1000, 1000),
    )

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
        ("session-1", 1, 1100, 1100, 1100),
    )

    connection.execute(
        """
        INSERT INTO tool_uses (
            session_id,
            turn_index,
            timestamp_ms,
            tool_name,
            input_hash,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        ("session-1", 1, 1200, "Bash", "abc123", 1200),
    )

    connection.execute(
        """
        INSERT INTO signals (
            session_id,
            turn_index,
            timestamp_ms,
            signal_type,
            score,
            confidence,
            health_score,
            state_before,
            state_after,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            "session-1",
            1,
            1300,
            "repeated_calls",
            0.6,
            1.0,
            0.72,
            "healthy",
            "watching",
            1300,
        ),
    )

    connection.execute(
        """
        INSERT INTO alerts (
            session_id,
            turn_index,
            timestamp_ms,
            alert_type,
            severity,
            message,
            signal_type,
            health_score,
            state,
            delivered_to,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            "session-1",
            1,
            1400,
            "degradation_warning",
            "warning",
            "Repeated tool calls detected.",
            "repeated_calls",
            0.72,
            "watching",
            "claude",
            1400,
        ),
    )

    assert connection.execute("SELECT COUNT(*) FROM tool_uses;").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM signals;").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM alerts;").fetchone()[0] == 1
