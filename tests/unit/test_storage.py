from __future__ import annotations

from pathlib import Path

import pytest

from pilot_core.constants import SessionState
from pilot_core.storage import (
    PilotStorage,
    SessionRecord,
    TurnRecord,
    open_storage,
    storage_context,
)


def test_session_repository_create_and_get(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with PilotStorage(db_path) as storage:
        created = storage.sessions.create(
            session_id="session-1",
            started_at=1000,
            cwd="D:/pilot/pilot",
            model="claude-sonnet",
            parent_session_id=None,
        )

        loaded = storage.sessions.get("session-1")

    assert isinstance(created, SessionRecord)
    assert loaded == created
    assert created.id == "session-1"
    assert created.started_at == 1000
    assert created.cwd == "D:/pilot/pilot"
    assert created.model == "claude-sonnet"
    assert created.state is SessionState.HEALTHY
    assert created.total_input_tokens == 0
    assert created.total_output_tokens == 0


def test_session_repository_create_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with PilotStorage(db_path) as storage:
        first = storage.sessions.create(session_id="session-1", started_at=1000)
        second = storage.sessions.create(session_id="session-1", started_at=2000)

    assert first == second
    assert second.started_at == 1000


def test_session_repository_update_state_and_end(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with PilotStorage(db_path) as storage:
        storage.sessions.create(session_id="session-1", started_at=1000)

        updated = storage.sessions.update_state("session-1", SessionState.WATCHING)
        ended = storage.sessions.end("session-1", ended_at=5000)

    assert updated.state is SessionState.WATCHING
    assert ended.state is SessionState.WATCHING
    assert ended.ended_at == 5000


def test_session_repository_token_usage_and_handoff_path(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    handoff_path = tmp_path / "handoffs" / "session-1.md"

    with PilotStorage(db_path) as storage:
        storage.sessions.create(session_id="session-1", started_at=1000)
        usage = storage.sessions.add_token_usage(
            "session-1",
            input_tokens=100,
            output_tokens=25,
            estimated_cost_usd=0.01,
        )
        updated = storage.sessions.set_handoff_summary_path("session-1", handoff_path)

    assert usage.total_input_tokens == 100
    assert usage.total_output_tokens == 25
    assert usage.estimated_cost_usd == pytest.approx(0.01)
    assert updated.handoff_summary_path == str(handoff_path)


def test_session_repository_list_recent(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with PilotStorage(db_path) as storage:
        storage.sessions.create(session_id="old", started_at=1000)
        storage.sessions.create(session_id="new", started_at=2000)

        records = storage.sessions.list_recent(limit=2)

    assert [record.id for record in records] == ["new", "old"]


def test_turn_repository_start_get_and_latest(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with PilotStorage(db_path) as storage:
        storage.sessions.create(session_id="session-1", started_at=1000)
        created = storage.turns.start(
            session_id="session-1",
            turn_index=0,
            started_at=1100,
            user_prompt_preview="hello",
        )
        loaded = storage.turns.get(session_id="session-1", turn_index=0)
        latest = storage.turns.latest("session-1")

    assert isinstance(created, TurnRecord)
    assert loaded == created
    assert latest == created
    assert created.session_id == "session-1"
    assert created.turn_index == 0
    assert created.started_at == 1100
    assert created.user_prompt_preview == "hello"
    assert created.tool_count == 0
    assert created.error_count == 0


def test_turn_repository_next_turn_index(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with PilotStorage(db_path) as storage:
        storage.sessions.create(session_id="session-1", started_at=1000)

        first_index = storage.turns.next_turn_index("session-1")
        storage.turns.start(session_id="session-1", turn_index=first_index, started_at=1100)
        second_index = storage.turns.next_turn_index("session-1")

    assert first_index == 0
    assert second_index == 1


def test_turn_repository_end_and_increment_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with PilotStorage(db_path) as storage:
        storage.sessions.create(session_id="session-1", started_at=1000)
        storage.turns.start(session_id="session-1", turn_index=0, started_at=1100)

        after_tools = storage.turns.increment_tool_count(session_id="session-1", turn_index=0)
        after_errors = storage.turns.increment_error_count(session_id="session-1", turn_index=0)
        ended = storage.turns.end(session_id="session-1", turn_index=0, ended_at=1500)

    assert after_tools.tool_count == 1
    assert after_errors.error_count == 1
    assert ended.tool_count == 1
    assert ended.error_count == 1
    assert ended.ended_at == 1500


def test_turn_repository_list_for_session(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with PilotStorage(db_path) as storage:
        storage.sessions.create(session_id="session-1", started_at=1000)
        storage.turns.start(session_id="session-1", turn_index=0, started_at=1100)
        storage.turns.start(session_id="session-1", turn_index=1, started_at=1200)

        records = storage.turns.list_for_session("session-1")

    assert [record.turn_index for record in records] == [0, 1]


def test_turn_repository_missing_increment_raises_key_error(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    with PilotStorage(db_path) as storage:
        storage.sessions.create(session_id="session-1", started_at=1000)

        with pytest.raises(KeyError):
            storage.turns.increment_tool_count(session_id="session-1", turn_index=99)


def test_open_storage_and_storage_context(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"

    storage = open_storage(db_path)
    try:
        storage.sessions.create(session_id="session-1", started_at=1000)
    finally:
        storage.close()

    with storage_context(db_path) as reopened:
        loaded = reopened.sessions.get("session-1")

    assert loaded is not None
    assert loaded.id == "session-1"
