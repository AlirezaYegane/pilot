"""Day 53 session CLI smoke report."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def create_sample_db(path: Path) -> None:
    """Create a small Day 53 smoke database."""

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
                "smoke-degraded",
                "degrading",
                0.43,
                1_700_000_000_000,
                None,
                ".pilot/handoffs/smoke-degraded.md",
            ),
        )
        conn.execute(
            """
            INSERT INTO sessions
            (id, state, health_score, started_at, ended_at, handoff_summary_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("smoke-healthy", "healthy", 0.94, 1_700_000_100_000, None, None),
        )
        conn.execute(
            """
            INSERT INTO tool_uses
            (session_id, tool_name, success, timestamp_ms, total_tokens, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("smoke-degraded", "Edit", 0, 1_700_000_010_000, 700, "patch failed"),
        )
        conn.execute(
            """
            INSERT INTO signals
            (session_id, signal_name, score, confidence, fired, explanation, timestamp_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "smoke-degraded",
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


def main() -> None:
    """Run the Day 53 smoke report."""

    from pilot_core.render.session_view import (
        session_detail_summary,
        session_list_summary,
    )
    from pilot_core.session_cli import (
        load_session_detail_from_db,
        load_session_list_from_db,
        run_sessions_command,
        run_show_command,
    )

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pilot.db"
        create_sample_db(db_path)

        sessions = load_session_list_from_db(db_path)
        detail = load_session_detail_from_db(db_path, "smoke-degraded")

        sessions_out = StringIO()
        show_out = StringIO()

        sessions_code = run_sessions_command(db_path=db_path, out=sessions_out)
        show_code = run_show_command(
            db_path=db_path,
            session_id="smoke-degraded",
            out=show_out,
        )

        summary = {
            "sessions_code": sessions_code,
            "show_code": show_code,
            "session_list": session_list_summary(sessions),
            "detail": session_detail_summary(detail) if detail is not None else None,
            "sessions_preview": sessions_out.getvalue().splitlines()[:6],
            "show_preview": show_out.getvalue().splitlines()[:10],
        }

        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
