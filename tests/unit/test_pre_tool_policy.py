from __future__ import annotations

import sqlite3
from pathlib import Path

from pilot_core.constants import SessionState
from pilot_core.pre_tool_policy import (
    evaluate_pre_tool_policy,
    parse_pre_tool_payload,
    read_pre_tool_snapshot,
    stable_tool_input_hash,
)


def _create_pre_tool_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL
            );

            CREATE TABLE tool_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                input_hash TEXT NOT NULL
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_parse_pre_tool_payload_accepts_snake_case() -> None:
    payload = {
        "session_id": "session-1",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
    }

    parsed = parse_pre_tool_payload(payload)

    assert parsed.session_id == "session-1"
    assert parsed.tool_name == "Bash"
    assert parsed.tool_input == {"command": "git status"}


def test_parse_pre_tool_payload_accepts_camel_case() -> None:
    payload = {
        "sessionId": "session-2",
        "toolName": "Read",
        "toolInput": {"file_path": "README.md"},
    }

    parsed = parse_pre_tool_payload(payload)

    assert parsed.session_id == "session-2"
    assert parsed.tool_name == "Read"
    assert parsed.tool_input == {"file_path": "README.md"}


def test_stable_tool_input_hash_is_order_insensitive_for_dicts() -> None:
    first = stable_tool_input_hash("Bash", {"a": 1, "b": 2})
    second = stable_tool_input_hash("Bash", {"b": 2, "a": 1})

    assert first == second


def test_missing_database_allows_tool_call(tmp_path: Path) -> None:
    decision = evaluate_pre_tool_policy(
        {
            "session_id": "session-1",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        },
        db_path=tmp_path / "missing.db",
    )

    assert decision.allowed
    assert decision.to_hook_stdout() == {}


def test_read_pre_tool_snapshot_reads_state_and_repeat_count(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_pre_tool_db(db_path)

    input_hash = stable_tool_input_hash("Bash", {"command": "git status"})

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT INTO sessions (id, state) VALUES (?, ?);",
            ("session-1", SessionState.HEALTHY.value),
        )
        for timestamp_ms in (100, 200, 300):
            connection.execute(
                """
                INSERT INTO tool_uses (session_id, timestamp_ms, input_hash)
                VALUES (?, ?, ?);
                """,
                ("session-1", timestamp_ms, input_hash),
            )
        connection.commit()
    finally:
        connection.close()

    snapshot = read_pre_tool_snapshot(
        session_id="session-1",
        input_hash=input_hash,
        db_path=db_path,
    )

    assert snapshot.session_state == SessionState.HEALTHY.value
    assert snapshot.recent_same_input_count == 3


def test_repeated_tool_call_adds_additional_context(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_pre_tool_db(db_path)

    payload = {
        "session_id": "session-1",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
    }
    input_hash = stable_tool_input_hash("Bash", {"command": "git status"})

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT INTO sessions (id, state) VALUES (?, ?);",
            ("session-1", SessionState.HEALTHY.value),
        )
        for timestamp_ms in (100, 200, 300):
            connection.execute(
                """
                INSERT INTO tool_uses (session_id, timestamp_ms, input_hash)
                VALUES (?, ?, ?);
                """,
                ("session-1", timestamp_ms, input_hash),
            )
        connection.commit()
    finally:
        connection.close()

    decision = evaluate_pre_tool_policy(payload, db_path=db_path)

    assert decision.allowed
    assert "repeated" in decision.additional_context.lower()
    assert "additionalContext" in decision.to_hook_stdout()


def test_handoff_state_can_block_when_explicitly_enabled(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_pre_tool_db(db_path)

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT INTO sessions (id, state) VALUES (?, ?);",
            ("session-1", SessionState.HANDOFF_PENDING.value),
        )
        connection.commit()
    finally:
        connection.close()

    decision = evaluate_pre_tool_policy(
        {
            "session_id": "session-1",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
        },
        db_path=db_path,
        block_on_handoff=True,
    )

    assert not decision.allowed
    assert decision.to_hook_stdout()["decision"] == "block"
