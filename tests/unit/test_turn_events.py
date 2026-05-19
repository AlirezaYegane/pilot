from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pilot_core.turn_events import prompt_preview, record_user_prompt_turn


def test_prompt_preview_collapses_whitespace_and_limits_length() -> None:
    prompt = "  hello\n\n   world   " + ("x" * 300)

    preview = prompt_preview(prompt, limit=20)

    assert preview == "hello world xxxxxxxx"


def test_record_user_prompt_turn_creates_session_and_first_turn(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    result = record_user_prompt_turn(
        {
            "session_id": "session-1",
            "cwd": "D:/pilot/pilot",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Build the next hook",
        },
        db_path=db_path,
        now_ms=1000,
    )

    assert result.session_id == "session-1"
    assert result.turn_index == 0
    assert result.prompt_preview == "Build the next hook"
    assert result.started_at == 1000

    with sqlite3.connect(db_path) as connection:
        session_row = connection.execute(
            "SELECT id, started_at, cwd, state FROM sessions WHERE id = ?;",
            ("session-1",),
        ).fetchone()
        turn_row = connection.execute(
            """
            SELECT session_id, turn_index, started_at, user_prompt_preview,
                   tool_count, error_count
            FROM turns
            WHERE session_id = ?;
            """,
            ("session-1",),
        ).fetchone()

    assert session_row == ("session-1", 1000, "D:/pilot/pilot", "healthy")
    assert turn_row == ("session-1", 0, 1000, "Build the next hook", 0, 0)


def test_record_user_prompt_turn_increments_turn_index(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    first = record_user_prompt_turn(
        {"session_id": "session-1", "prompt": "first"},
        db_path=db_path,
        now_ms=1000,
    )
    second = record_user_prompt_turn(
        {"session_id": "session-1", "prompt": "second"},
        db_path=db_path,
        now_ms=2000,
    )

    assert first.turn_index == 0
    assert second.turn_index == 1

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT turn_index, started_at, ended_at, user_prompt_preview,
                   tool_count, error_count
            FROM turns
            WHERE session_id = ?
            ORDER BY turn_index;
            """,
            ("session-1",),
        ).fetchall()

    assert rows == [
        (0, 1000, 2000, "first", 0, 0),
        (1, 2000, None, "second", 0, 0),
    ]


def test_record_user_prompt_turn_requires_session_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="session_id"):
        record_user_prompt_turn(
            {"prompt": "missing session id"},
            db_path=tmp_path / "pilot.db",
        )


def test_record_user_prompt_turn_handles_missing_prompt(tmp_path: Path) -> None:
    result = record_user_prompt_turn(
        {"session_id": "session-1"},
        db_path=tmp_path / "pilot.db",
        now_ms=1000,
    )

    assert result.prompt_preview == ""
