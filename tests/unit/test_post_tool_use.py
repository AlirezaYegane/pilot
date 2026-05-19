from __future__ import annotations

import sqlite3
from pathlib import Path

from pilot_core.post_tool_use import handle_post_tool_use, record_post_tool_use
from pilot_core.token_estimation import estimate_token_count, payload_size_bytes, stable_json_dumps


def _create_day19_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL,
                state TEXT DEFAULT 'healthy',
                total_input_tokens INTEGER DEFAULT 0,
                total_output_tokens INTEGER DEFAULT 0
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                turn_index INTEGER,
                started_at INTEGER,
                tool_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            """
        )
        conn.execute(
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
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (id, started_at, state)
            VALUES ('session-1', 1000, 'healthy');
            """
        )
        conn.execute(
            """
            INSERT INTO turns (session_id, turn_index, started_at)
            VALUES ('session-1', 1, 1000);
            """
        )
        conn.commit()


def test_stable_json_dumps_sorts_keys() -> None:
    assert stable_json_dumps({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_estimate_token_count_returns_positive_for_text() -> None:
    assert estimate_token_count("hello world") > 0


def test_payload_size_bytes_uses_utf8() -> None:
    assert payload_size_bytes("سلام") == len("سلام".encode())


def test_record_post_tool_use_inserts_successful_tool_event(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_day19_schema(db_path)

    payload = {
        "session_id": "session-1",
        "turn_index": 1,
        "timestamp_ms": 2000,
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "tool_response": {"stdout": "clean", "stderr": ""},
        "duration_ms": 42,
    }

    result = record_post_tool_use(payload, db_path=db_path)

    assert result.recorded
    assert result.session_id == "session-1"
    assert result.tool_name == "Bash"
    assert result.turn_index == 1
    assert result.input_tokens_est > 0
    assert result.output_tokens_est > 0
    assert len(result.input_hash) == 64

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT session_id, turn_index, tool_name, success, duration_ms,
                   input_tokens_est, output_tokens_est
            FROM tool_uses;
            """
        ).fetchone()

        assert row == (
            "session-1",
            1,
            "Bash",
            1,
            42,
            result.input_tokens_est,
            result.output_tokens_est,
        )

        turn_tool_count = conn.execute(
            """
            SELECT tool_count FROM turns
            WHERE session_id = 'session-1' AND turn_index = 1;
            """
        ).fetchone()[0]
        assert turn_tool_count == 1

        session_totals = conn.execute(
            """
            SELECT total_input_tokens, total_output_tokens
            FROM sessions
            WHERE id = 'session-1';
            """
        ).fetchone()
        assert session_totals == (result.input_tokens_est, result.output_tokens_est)


def test_record_post_tool_use_uses_latest_turn_when_turn_index_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_day19_schema(db_path)

    payload = {
        "session_id": "session-1",
        "timestamp_ms": 2000,
        "tool_name": "Read",
        "tool_input": {"file_path": "README.md"},
        "tool_response": "content",
    }

    result = record_post_tool_use(payload, db_path=db_path)

    assert result.recorded
    assert result.turn_index == 1


def test_record_post_tool_use_creates_placeholder_session_when_needed(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_day19_schema(db_path)

    payload = {
        "session_id": "new-session",
        "timestamp_ms": 3000,
        "tool_name": "Glob",
        "tool_input": {"pattern": "*.py"},
        "tool_response": {"files": ["a.py"]},
    }

    result = record_post_tool_use(payload, db_path=db_path)

    assert result.recorded

    with sqlite3.connect(db_path) as conn:
        session = conn.execute(
            "SELECT id, state FROM sessions WHERE id = 'new-session';"
        ).fetchone()
        assert session == ("new-session", "healthy")


def test_record_post_tool_use_returns_false_when_table_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL
            );
            """
        )
        conn.commit()

    result = record_post_tool_use(
        {
            "session_id": "session-1",
            "tool_name": "Bash",
            "tool_input": {},
            "tool_response": {},
        },
        db_path=db_path,
    )

    assert not result.recorded
    assert result.reason == "tool_uses_table_missing"


def test_record_post_tool_use_returns_false_without_session_id(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_day19_schema(db_path)

    result = record_post_tool_use(
        {
            "tool_name": "Bash",
            "tool_input": {},
            "tool_response": {},
        },
        db_path=db_path,
    )

    assert not result.recorded
    assert result.reason == "missing_session_id"


def test_handle_post_tool_use_accepts_non_mapping_payload() -> None:
    result = handle_post_tool_use("not-json-object")

    assert not result.recorded
    assert result.reason == "missing_session_id"
