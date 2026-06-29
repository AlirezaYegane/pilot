from __future__ import annotations

import sqlite3
from io import StringIO
from pathlib import Path

from pilot_core.session_cli import (
    load_session_detail_from_db,
    load_session_list_from_db,
    run_sessions_command,
    run_show_command,
)


def create_sample_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                health_score REAL,
                started_at INTEGER,
                ended_at INTEGER,
                handoff_summary_path TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE tool_uses (
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                success INTEGER NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE signals (
                session_id TEXT NOT NULL,
                signal_name TEXT NOT NULL,
                score REAL NOT NULL,
                confidence REAL NOT NULL,
                fired INTEGER NOT NULL,
                explanation TEXT,
                timestamp_ms INTEGER
            )
            """
        )

        conn.execute(
            """
            INSERT INTO sessions
            (id, state, health_score, started_at, ended_at, handoff_summary_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "session-degraded",
                "degrading",
                0.42,
                1_700_000_000_000,
                None,
                ".pilot/handoffs/session-degraded.md",
            ),
        )
        conn.execute(
            """
            INSERT INTO sessions
            (id, state, health_score, started_at, ended_at, handoff_summary_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("session-healthy", "healthy", 0.91, 1_700_000_100_000, None, None),
        )
        conn.execute(
            """
            INSERT INTO tool_uses
            (session_id, tool_name, success, timestamp_ms, total_tokens, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("session-degraded", "Edit", 0, 1_700_000_010_000, 700, "patch failed"),
        )
        conn.execute(
            """
            INSERT INTO signals
            (session_id, signal_name, score, confidence, fired, explanation, timestamp_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "session-degraded",
                "error_cascade",
                0.82,
                0.90,
                1,
                "Repeated failing tool calls",
                1_700_000_020_000,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_load_session_list_from_db(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    create_sample_db(db_path)

    sessions = load_session_list_from_db(db_path)

    assert len(sessions) == 2
    assert any(item.session_id == "session-degraded" for item in sessions)
    degraded = next(item for item in sessions if item.session_id == "session-degraded")
    assert degraded.tool_call_count == 1
    assert degraded.signal_count == 1
    assert degraded.total_tokens == 700


def test_load_session_detail_from_db(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    create_sample_db(db_path)

    detail = load_session_detail_from_db(db_path, "session-degraded")

    assert detail is not None
    assert detail.session.session_id == "session-degraded"
    assert len(detail.tools) == 1
    assert len(detail.signals) == 1
    assert detail.signals[0].fired is True


def test_run_sessions_command_renders_text(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    create_sample_db(db_path)

    out = StringIO()
    code = run_sessions_command(db_path=db_path, out=out)

    assert code == 0
    text = out.getvalue()
    assert "Pilot sessions" in text
    assert "session-degraded" in text


def test_run_show_command_renders_detail(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    create_sample_db(db_path)

    out = StringIO()
    err = StringIO()
    code = run_show_command(
        db_path=db_path,
        session_id="session-degraded",
        out=out,
        err=err,
    )

    assert code == 0
    text = out.getvalue()
    assert "Pilot session: session-degraded" in text
    assert "error_cascade" in text
    assert "patch failed" in text


def test_run_show_command_returns_one_for_missing_session(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    create_sample_db(db_path)

    out = StringIO()
    err = StringIO()
    code = run_show_command(
        db_path=db_path,
        session_id="missing",
        out=out,
        err=err,
    )

    assert code == 1
    assert "not found" in err.getvalue()
