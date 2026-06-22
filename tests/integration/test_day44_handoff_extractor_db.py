from __future__ import annotations

import sqlite3

from pilot_core.handoff_extractor import extract_handoff_from_db


def _build_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")

    connection.execute(
        """
        CREATE TABLE events (
            session_id TEXT,
            turn_index INTEGER,
            role TEXT,
            content TEXT,
            summary TEXT,
            tool_name TEXT,
            file_path TEXT,
            success INTEGER,
            timestamp_ms INTEGER
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE signals (
            session_id TEXT,
            turn_index INTEGER,
            signal_name TEXT,
            score REAL,
            fired INTEGER,
            severity TEXT,
            timestamp_ms INTEGER
        )
        """
    )

    events = [
        (
            "day44-session",
            1,
            "user",
            "Create a DB summary extractor for handoff",
            "",
            "",
            "",
            1,
            1000,
        ),
        (
            "day44-session",
            2,
            "assistant",
            "",
            "Decision: keep Day 44 extractor separate from markdown rendering",
            "",
            "",
            1,
            2000,
        ),
        (
            "day44-session",
            3,
            "tool",
            "",
            "",
            "Write",
            "pilot_core/handoff_extractor.py",
            1,
            3000,
        ),
        (
            "day44-session",
            4,
            "assistant",
            "",
            "Next step: run full quality gate and commit",
            "",
            "",
            1,
            4000,
        ),
    ]

    signals = [
        ("day44-session", 3, "token_burn", 0.20, 0, "info", 3100),
        ("day44-session", 4, "error_cascade", 0.88, 1, "warning", 4100),
    ]

    connection.executemany(
        """
        INSERT INTO events
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        events,
    )
    connection.executemany(
        """
        INSERT INTO signals
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        signals,
    )
    connection.commit()

    return connection


def test_day44_db_extractor_generates_valid_handoff() -> None:
    connection = _build_connection()

    result = extract_handoff_from_db(connection, session_id="day44-session")

    assert result.is_valid
    assert result.handoff.session_id == "day44-session"
    assert result.handoff.task == "Create a DB summary extractor for handoff"
    assert result.handoff.files_modified[0].path == "pilot_core/handoff_extractor.py"
    assert result.handoff.decisions
    assert "Signal history" in result.handoff.notes[0]


def test_day44_db_extractor_filters_session_id() -> None:
    connection = _build_connection()
    connection.execute(
        """
        INSERT INTO events
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "other-session",
            1,
            "user",
            "This should not leak into the target handoff",
            "",
            "",
            "",
            1,
            9999,
        ),
    )
    connection.commit()

    result = extract_handoff_from_db(connection, session_id="day44-session")

    assert "other-session" not in result.handoff.task
    assert result.handoff.session_id == "day44-session"


def test_day44_db_extractor_handles_missing_tables() -> None:
    connection = sqlite3.connect(":memory:")

    result = extract_handoff_from_db(connection, session_id="missing-tables")

    assert result.is_valid
    assert result.handoff.task == "Continue Pilot session"
    assert result.key_turns == tuple()
    assert result.signal_history == tuple()
