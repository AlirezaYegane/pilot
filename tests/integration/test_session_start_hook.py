from __future__ import annotations

import sqlite3
from pathlib import Path

from pilot_core.hook_handlers.session_start import (
    SessionStartPayload,
    handle_session_start,
    load_hook_payload,
    parse_session_start_payload,
    record_session_start,
)
from pilot_core.paths import RuntimePaths


def _runtime_paths(tmp_path: Path) -> RuntimePaths:
    return RuntimePaths(
        data_dir=tmp_path / "data",
        handoff_dir=tmp_path / "data" / "handoffs",
        temp_dir=tmp_path / "data" / "tmp",
        debug_log_path=tmp_path / "debug.log",
        db_path=tmp_path / "data" / "pilot.db",
    )


def _create_sessions_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                cwd TEXT,
                model TEXT,
                parent_session_id TEXT,
                total_input_tokens INTEGER DEFAULT 0,
                total_output_tokens INTEGER DEFAULT 0,
                estimated_cost_usd REAL DEFAULT 0,
                state TEXT DEFAULT 'healthy',
                handoff_summary_path TEXT
            );
            """
        )


def test_load_hook_payload_accepts_json_object() -> None:
    payload = load_hook_payload('{"session_id": "abc-123"}')
    assert payload == {"session_id": "abc-123"}


def test_load_hook_payload_accepts_empty_stdin() -> None:
    assert load_hook_payload("") == {}


def test_parse_session_start_payload_accepts_snake_case() -> None:
    payload = parse_session_start_payload(
        {
            "session_id": "abc-123",
            "timestamp_ms": 123,
            "cwd": "D:/pilot/pilot",
            "model": "claude-sonnet",
            "parent_session_id": "parent-1",
        }
    )

    assert payload.session_id == "abc-123"
    assert payload.started_at_ms == 123
    assert payload.cwd == "D:/pilot/pilot"
    assert payload.model == "claude-sonnet"
    assert payload.parent_session_id == "parent-1"


def test_parse_session_start_payload_accepts_camel_case() -> None:
    payload = parse_session_start_payload(
        {
            "sessionId": "abc-456",
            "timestampMs": "456",
            "workspaceDir": "D:/pilot",
            "modelName": "claude-opus",
            "parentSessionId": "parent-2",
        }
    )

    assert payload.session_id == "abc-456"
    assert payload.started_at_ms == 456
    assert payload.cwd == "D:/pilot"
    assert payload.model == "claude-opus"
    assert payload.parent_session_id == "parent-2"


def test_record_session_start_inserts_session(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_sessions_table(db_path)

    payload = SessionStartPayload(
        session_id="session-1",
        started_at_ms=1000,
        cwd="D:/pilot/pilot",
        model="claude-sonnet",
        parent_session_id=None,
    )

    with sqlite3.connect(db_path) as connection:
        record_session_start(connection, payload)
        row = connection.execute(
            """
            SELECT id, started_at, ended_at, cwd, model, parent_session_id, state
            FROM sessions
            WHERE id = ?;
            """,
            ("session-1",),
        ).fetchone()

    assert row == (
        "session-1",
        1000,
        None,
        "D:/pilot/pilot",
        "claude-sonnet",
        None,
        "healthy",
    )


def test_record_session_start_is_idempotent_and_reopens_session(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_sessions_table(db_path)

    first_payload = SessionStartPayload(
        session_id="session-1",
        started_at_ms=1000,
        cwd="D:/pilot/old",
        model="claude-sonnet",
        parent_session_id="parent-1",
    )
    second_payload = SessionStartPayload(
        session_id="session-1",
        started_at_ms=9999,
        cwd="D:/pilot/new",
        model="claude-opus",
        parent_session_id=None,
    )

    with sqlite3.connect(db_path) as connection:
        record_session_start(connection, first_payload)
        connection.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?;",
            (2000, "session-1"),
        )
        connection.commit()

        record_session_start(connection, second_payload)

        rows = connection.execute(
            """
            SELECT id, started_at, ended_at, cwd, model, parent_session_id, state
            FROM sessions
            WHERE id = ?;
            """,
            ("session-1",),
        ).fetchall()

    assert rows == [
        (
            "session-1",
            1000,
            None,
            "D:/pilot/new",
            "claude-opus",
            "parent-1",
            "healthy",
        )
    ]


def test_handle_session_start_records_session(tmp_path: Path) -> None:
    paths = _runtime_paths(tmp_path)
    _create_sessions_table(paths.db_path)

    ok = handle_session_start(
        {
            "session_id": "session-2",
            "timestamp_ms": 3000,
            "cwd": "D:/pilot/pilot",
            "model": "claude-sonnet",
        },
        paths=paths,
    )

    with sqlite3.connect(paths.db_path) as connection:
        row = connection.execute(
            "SELECT id, started_at, cwd, model, state FROM sessions WHERE id = ?;",
            ("session-2",),
        ).fetchone()

    assert ok is True
    assert row == ("session-2", 3000, "D:/pilot/pilot", "claude-sonnet", "healthy")


def test_handle_session_start_fails_silently_when_payload_is_invalid(tmp_path: Path) -> None:
    paths = _runtime_paths(tmp_path)
    _create_sessions_table(paths.db_path)

    ok = handle_session_start({}, paths=paths)

    assert ok is False
