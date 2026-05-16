from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pilot_core.storage import (
    SignalEventCreate,
    SignalEventRepository,
    ToolUseCreate,
    ToolUseRepository,
    ensure_storage_schema,
    get_storage_repositories,
    record_signal_event,
    record_tool_use,
    storage_transaction,
)


def _create_session(db_path: Path, session_id: str = "session-1") -> None:
    ensure_storage_schema(db_path)

    with storage_transaction(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, started_at, state) VALUES (?, ?, ?);",
            (session_id, 1000, "healthy"),
        )


def test_storage_transaction_commits_successful_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    ensure_storage_schema(db_path)

    with storage_transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, started_at, state) VALUES (?, ?, ?);",
            ("session-commit", 1000, "healthy"),
        )

    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE id = ?;",
            ("session-commit",),
        ).fetchone()[0]

    assert count == 1


def test_storage_transaction_rolls_back_failed_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    ensure_storage_schema(db_path)

    with (
        pytest.raises(RuntimeError, match="force rollback"),
        storage_transaction(db_path) as conn,
    ):
        conn.execute(
            "INSERT INTO sessions (id, started_at, state) VALUES (?, ?, ?);",
            ("session-rollback", 1000, "healthy"),
        )
        raise RuntimeError("force rollback")

    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE id = ?;",
            ("session-rollback",),
        ).fetchone()[0]

    assert count == 0


def test_tool_use_repository_insert_and_list(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_session(db_path)

    repository = ToolUseRepository(db_path)
    row_id = repository.insert(
        ToolUseCreate(
            session_id="session-1",
            turn_index=2,
            timestamp_ms=1234,
            tool_name="Bash",
            input_payload={"cmd": "pytest"},
            output_payload={"stdout": "passed"},
            success=True,
            duration_ms=50,
            input_tokens_est=10,
            output_tokens_est=20,
        )
    )

    records = repository.list_for_session("session-1")

    assert row_id > 0
    assert len(records) == 1
    assert records[0].session_id == "session-1"
    assert records[0].turn_index == 2
    assert records[0].timestamp_ms == 1234
    assert records[0].tool_name == "Bash"
    assert records[0].success is True
    assert records[0].duration_ms == 50
    assert records[0].input_tokens_est == 10
    assert records[0].output_tokens_est == 20
    assert len(records[0].input_hash) == 64


def test_tool_use_repository_counts_repeated_calls(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_session(db_path)

    repository = ToolUseRepository(db_path)
    payload = {"cmd": "ruff check ."}
    first_id = repository.insert(
        ToolUseCreate(
            session_id="session-1",
            timestamp_ms=1000,
            tool_name="Bash",
            input_payload=payload,
        )
    )

    first_record = repository.list_for_session("session-1")[0]

    repository.insert(
        ToolUseCreate(
            session_id="session-1",
            timestamp_ms=1001,
            tool_name="Bash",
            input_payload=payload,
        )
    )
    repository.insert(
        ToolUseCreate(
            session_id="session-1",
            timestamp_ms=1002,
            tool_name="Bash",
            input_payload=payload,
        )
    )

    repeated_count = repository.count_repeated(
        session_id="session-1",
        tool_name="Bash",
        input_hash=first_record.input_hash,
        window_size=10,
    )

    assert first_id > 0
    assert repeated_count == 3


def test_tool_use_repository_counts_recent_failures(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_session(db_path)

    repository = ToolUseRepository(db_path)

    repository.insert(
        ToolUseCreate(
            session_id="session-1",
            timestamp_ms=1000,
            tool_name="Bash",
            input_payload={"cmd": "pytest"},
            success=False,
        )
    )
    repository.insert(
        ToolUseCreate(
            session_id="session-1",
            timestamp_ms=1001,
            tool_name="Bash",
            input_payload={"cmd": "mypy pilot_core tests"},
            success=True,
        )
    )
    repository.insert(
        ToolUseCreate(
            session_id="session-1",
            timestamp_ms=1002,
            tool_name="Bash",
            input_payload={"cmd": "ruff check ."},
            success=False,
        )
    )

    assert repository.count_recent_failures(session_id="session-1", window_size=5) == 2


def test_signal_event_repository_insert_and_list(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_session(db_path)

    repository = SignalEventRepository(db_path)
    row_id = repository.insert(
        SignalEventCreate(
            session_id="session-1",
            timestamp_ms=2000,
            signal_type="repeated_calls",
            score=0.75,
            health_score=0.55,
            state_before="watching",
            state_after="degrading",
            metadata={"repeat_count": 3},
        )
    )

    records = repository.list_for_session("session-1")

    assert row_id > 0
    assert len(records) == 1
    assert records[0].session_id == "session-1"
    assert records[0].timestamp_ms == 2000
    assert records[0].signal_type == "repeated_calls"
    assert records[0].score == 0.75
    assert records[0].health_score == 0.55
    assert records[0].state_before == "watching"
    assert records[0].state_after == "degrading"
    assert records[0].metadata_json is not None
    assert "repeat_count" in records[0].metadata_json


def test_repository_bundle_shares_transaction_connection(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    ensure_storage_schema(db_path)

    with storage_transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, started_at, state) VALUES (?, ?, ?);",
            ("session-1", 1000, "healthy"),
        )

        repositories = get_storage_repositories(connection=conn)

        repositories.tool_uses.insert(
            ToolUseCreate(
                session_id="session-1",
                timestamp_ms=3000,
                tool_name="Read",
                input_payload={"file": "README.md"},
            )
        )
        repositories.signals.insert(
            SignalEventCreate(
                session_id="session-1",
                timestamp_ms=3001,
                signal_type="token_burn",
                score=0.2,
            )
        )

    assert ToolUseRepository(db_path).list_for_session("session-1")[0].tool_name == "Read"
    assert (
        SignalEventRepository(db_path).list_for_session("session-1")[0].signal_type == "token_burn"
    )


def test_convenience_record_helpers(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    _create_session(db_path)

    tool_row_id = record_tool_use(
        session_id="session-1",
        tool_name="Edit",
        input_payload={"file": "pilot_core/storage.py"},
        output_payload={"ok": True},
        db_path=db_path,
    )
    signal_row_id = record_signal_event(
        session_id="session-1",
        signal_type="low_productivity",
        score=0.4,
        metadata={"ratio": 0.45},
        db_path=db_path,
    )

    assert tool_row_id > 0
    assert signal_row_id > 0
    assert ToolUseRepository(db_path).list_for_session("session-1")[0].tool_name == "Edit"
    assert (
        SignalEventRepository(db_path).list_for_session("session-1")[0].signal_type
        == "low_productivity"
    )
