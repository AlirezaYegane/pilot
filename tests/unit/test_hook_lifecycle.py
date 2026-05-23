from __future__ import annotations

import sqlite3
from pathlib import Path

from pilot_core.constants import SessionState
from pilot_core.hook_lifecycle import (
    extract_session_id,
    process_session_end_payload,
    process_stop_payload,
)
from pilot_core.paths import RuntimePaths, ensure_runtime_dirs


def _runtime_paths(tmp_path: Path) -> RuntimePaths:
    return RuntimePaths(
        data_dir=tmp_path / "data",
        handoff_dir=tmp_path / "data" / "handoffs",
        temp_dir=tmp_path / "data" / "tmp",
        debug_log_path=tmp_path / "debug.log",
        db_path=tmp_path / "data" / "pilot.db",
    )


def _create_sessions_table(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                cwd TEXT,
                model TEXT,
                state TEXT DEFAULT 'healthy',
                handoff_summary_path TEXT
            );
            """
        )
        conn.commit()


def _session_row(db_path: Path, session_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sessions WHERE id = ?;", (session_id,)).fetchone()
    conn.close()
    assert isinstance(row, sqlite3.Row)
    return row


def test_extract_session_id_accepts_snake_case() -> None:
    assert extract_session_id({"session_id": "abc-123"}) == "abc-123"


def test_extract_session_id_accepts_camel_case() -> None:
    assert extract_session_id({"sessionId": "abc-456"}) == "abc-456"


def test_stop_payload_writes_handoff_placeholder(tmp_path: Path) -> None:
    paths = ensure_runtime_dirs(_runtime_paths(tmp_path))
    _create_sessions_table(paths.db_path)

    payload = {
        "session_id": "day21-stop-unit",
        "cwd": "D:/pilot/pilot",
        "model": "claude-test",
    }

    result = process_stop_payload(payload, paths=paths)

    assert result.event == "Stop"
    assert result.session_id == "day21-stop-unit"
    assert result.handoff_path is not None
    assert result.handoff_path.exists()
    assert "Pilot Handoff Placeholder" in result.handoff_path.read_text(encoding="utf-8")

    row = _session_row(paths.db_path, "day21-stop-unit")
    assert row["handoff_summary_path"] == str(result.handoff_path)


def test_stop_payload_emits_context_for_critical_session(tmp_path: Path) -> None:
    paths = ensure_runtime_dirs(_runtime_paths(tmp_path))
    _create_sessions_table(paths.db_path)

    with sqlite3.connect(paths.db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, started_at, state) VALUES (?, ?, ?);",
            ("critical-session", 1, SessionState.CRITICAL.value),
        )
        conn.commit()

    result = process_stop_payload({"session_id": "critical-session"}, paths=paths)

    assert result.additional_context is not None
    assert "handoff" in result.additional_context.lower()

    row = _session_row(paths.db_path, "critical-session")
    assert row["state"] == SessionState.HANDOFF_PENDING.value


def test_session_end_payload_marks_session_ended(tmp_path: Path) -> None:
    paths = ensure_runtime_dirs(_runtime_paths(tmp_path))
    _create_sessions_table(paths.db_path)

    payload = {
        "session_id": "day21-end-unit",
        "cwd": "D:/pilot/pilot",
    }

    result = process_session_end_payload(payload, paths=paths)

    assert result.event == "SessionEnd"
    assert result.ended
    assert result.handoff_path is not None
    assert result.handoff_path.exists()

    row = _session_row(paths.db_path, "day21-end-unit")
    assert row["ended_at"] is not None
    assert row["handoff_summary_path"] == str(result.handoff_path)
