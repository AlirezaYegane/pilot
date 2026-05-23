from __future__ import annotations

import sqlite3
from pathlib import Path

from pilot_core.post_tool_failure import (
    normalize_failure_payload,
    record_tool_failure,
    stable_input_hash,
)


def _create_test_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL,
                state TEXT DEFAULT 'healthy'
            );
            """
        )
        connection.execute(
            """
            CREATE TABLE turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                started_at INTEGER,
                tool_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0
            );
            """
        )
        connection.execute(
            """
            CREATE TABLE tool_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_index INTEGER,
                timestamp_ms INTEGER,
                tool_name TEXT,
                input_hash TEXT,
                input_size INTEGER,
                output_size INTEGER,
                success INTEGER,
                duration_ms INTEGER,
                input_tokens_est INTEGER,
                output_tokens_est INTEGER,
                tool_input_json TEXT,
                error_type TEXT,
                error_message TEXT,
                error_payload_json TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            """
        )
        connection.execute(
            """
            INSERT INTO turns (
                session_id,
                turn_index,
                started_at,
                tool_count,
                error_count
            )
            VALUES (?, ?, ?, ?, ?);
            """,
            ("session-1", 2, 1000, 1, 0),
        )
        connection.commit()


def test_stable_input_hash_is_stable_for_same_payload() -> None:
    first = stable_input_hash("Bash", {"command": "pytest"})
    second = stable_input_hash("Bash", {"command": "pytest"})

    assert first == second
    assert len(first) == 64


def test_normalize_failure_payload_accepts_common_keys() -> None:
    record = normalize_failure_payload(
        {
            "session_id": "session-1",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
            "error": {"type": "RuntimeError", "message": "tests failed"},
            "timestamp_ms": 1234,
            "duration_ms": 55,
            "turn_index": 2,
        }
    )

    assert record.session_id == "session-1"
    assert record.tool_name == "Bash"
    assert record.tool_input == {"command": "pytest"}
    assert record.error_type == "RuntimeError"
    assert record.error_message == "tests failed"
    assert record.timestamp_ms == 1234
    assert record.duration_ms == 55
    assert record.turn_index == 2
    assert record.input_size > 0
    assert record.output_size > 0


def test_record_tool_failure_inserts_failed_tool_use_and_updates_turn(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "pilot.db"
    _create_test_db(db_path)

    record = normalize_failure_payload(
        {
            "session_id": "session-1",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
            "error": {"type": "RuntimeError", "message": "tests failed"},
            "timestamp_ms": 1234,
            "duration_ms": 55,
            "turn_index": 2,
        }
    )

    record_tool_failure(record, db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row

        tool_row = connection.execute(
            """
            SELECT *
            FROM tool_uses
            WHERE session_id = ?;
            """,
            ("session-1",),
        ).fetchone()

        assert tool_row is not None
        assert tool_row["tool_name"] == "Bash"
        assert tool_row["success"] == 0
        assert tool_row["error_type"] == "RuntimeError"
        assert tool_row["error_message"] == "tests failed"
        assert tool_row["input_tokens_est"] == 0
        assert tool_row["output_tokens_est"] == 0

        turn_row = connection.execute(
            """
            SELECT tool_count, error_count
            FROM turns
            WHERE session_id = ? AND turn_index = ?;
            """,
            ("session-1", 2),
        ).fetchone()

        assert turn_row is not None
        assert turn_row["tool_count"] == 2
        assert turn_row["error_count"] == 1


def test_record_tool_failure_creates_missing_session_row(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_test_db(db_path)

    record = normalize_failure_payload(
        {
            "session_id": "new-session",
            "tool_name": "Read",
            "tool_input": {"file_path": "missing.txt"},
            "error_message": "file not found",
            "timestamp_ms": 999,
        }
    )

    record_tool_failure(record, db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        session_row = connection.execute(
            "SELECT id, state FROM sessions WHERE id = ?;",
            ("new-session",),
        ).fetchone()

        assert session_row == ("new-session", "healthy")
