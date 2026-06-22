from __future__ import annotations

import sqlite3

from pilot_core.handoff import HandoffFileStatus, handoff_from_json, handoff_to_json
from pilot_core.handoff_extractor import (
    collect_key_turns,
    collect_signal_history,
    extract_handoff_from_db,
    extract_handoff_from_records,
    handoff_extraction_summary,
)


def test_collect_key_turns_keeps_user_failures_and_file_edits() -> None:
    rows: list[dict[str, object]] = [
        {
            "turn_index": 1,
            "role": "user",
            "content": "Implement Day 44 handoff extractor",
        },
        {
            "turn_index": 2,
            "role": "assistant",
            "summary": "Created extractor skeleton",
        },
        {
            "turn_index": 3,
            "tool_name": "Edit",
            "tool_input": {"file_path": "pilot_core/handoff_extractor.py"},
            "success": True,
        },
        {
            "turn_index": 4,
            "tool_name": "Bash",
            "content": "pytest failed",
            "success": False,
        },
    ]

    turns = collect_key_turns(rows)

    assert len(turns) == 4
    assert turns[0].role == "user"
    assert turns[2].file_path == "pilot_core/handoff_extractor.py"
    assert turns[3].success is False


def test_collect_signal_history_keeps_fired_and_nonzero_scores() -> None:
    rows: list[dict[str, object]] = [
        {"turn_index": 1, "signal_name": "token_burn", "score": 0.0, "fired": False},
        {"turn_index": 2, "signal_name": "error_cascade", "score": 0.9, "fired": True},
        {"turn_index": 3, "signal_name": "self_doubt", "score": 0.25, "fired": False},
    ]

    history = collect_signal_history(rows)

    assert [signal.signal_name for signal in history] == ["error_cascade", "self_doubt"]
    assert history[0].fired is True
    assert history[1].score == 0.25


def test_extract_handoff_from_records_builds_valid_schema() -> None:
    result = extract_handoff_from_records(
        session_id="session-44",
        turn_rows=[
            {
                "turn_index": 1,
                "role": "user",
                "content": "Implement Day 44 handoff summary extractor",
            },
            {
                "turn_index": 2,
                "role": "assistant",
                "summary": "Decision: keep extractor side-effect free",
            },
            {
                "turn_index": 3,
                "tool_name": "Write",
                "tool_input": {"file_path": "pilot_core/handoff_extractor.py"},
                "success": True,
            },
            {
                "turn_index": 4,
                "role": "assistant",
                "summary": "Next step: run targeted tests and smoke script",
            },
        ],
        signal_rows=[
            {
                "turn_index": 4,
                "signal_name": "context_saturation",
                "score": 0.72,
                "fired": True,
                "severity": "warning",
            }
        ],
    )

    assert result.is_valid
    assert result.handoff.session_id == "session-44"
    assert "Day 44" in result.handoff.task
    assert result.handoff.decisions[0].title.startswith("Decision:")
    assert result.handoff.files_modified[0].path == "pilot_core/handoff_extractor.py"
    assert result.handoff.files_modified[0].status is HandoffFileStatus.CREATED
    assert result.signal_history[0].signal_name == "context_saturation"
    assert "Signal history" in result.handoff.notes[0]


def test_extract_handoff_from_records_has_safe_fallbacks() -> None:
    result = extract_handoff_from_records(
        session_id=None,
        turn_rows=[],
        signal_rows=[],
    )

    assert result.is_valid
    assert result.handoff.task == "Continue Pilot session"
    assert result.handoff.files_modified == tuple()
    assert result.handoff.blockers == tuple()
    assert result.handoff.do_not_redo == tuple()


def test_handoff_extraction_summary_is_json_safe() -> None:
    result = extract_handoff_from_records(
        session_id="session-summary",
        turn_rows=[
            {
                "turn_index": 1,
                "role": "user",
                "content": "Summarise DB records",
            }
        ],
    )

    summary = handoff_extraction_summary(result)

    assert summary["source"] == "records"
    assert summary["session_id"] == "session-summary"
    assert summary["is_valid"] is True
    assert summary["key_turn_count"] == 1


def test_extracted_handoff_round_trips_through_json() -> None:
    result = extract_handoff_from_records(
        session_id="session-json",
        turn_rows=[
            {
                "turn_index": 1,
                "role": "user",
                "content": "Build extractor",
            }
        ],
    )

    text = handoff_to_json(result.handoff)
    parsed = handoff_from_json(text)

    assert parsed == result.handoff


def test_extract_handoff_from_db_reads_candidate_tables() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE session_turns (
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
        CREATE TABLE signal_results (
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
    connection.execute(
        """
        INSERT INTO session_turns
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "db-session",
            1,
            "user",
            "Implement DB handoff extractor",
            "",
            "",
            "",
            1,
            1000,
        ),
    )
    connection.execute(
        """
        INSERT INTO session_turns
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "db-session",
            2,
            "tool",
            "",
            "Extractor wrote a file",
            "Edit",
            "pilot_core/handoff_extractor.py",
            1,
            2000,
        ),
    )
    connection.execute(
        """
        INSERT INTO signal_results
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("db-session", 2, "error_cascade", 0.81, 1, "warning", 2100),
    )
    connection.commit()

    result = extract_handoff_from_db(connection, session_id="db-session")

    assert result.source == "sqlite"
    assert result.is_valid
    assert result.handoff.task == "Implement DB handoff extractor"
    assert result.handoff.files_modified[0].path == "pilot_core/handoff_extractor.py"
    assert result.signal_history[0].signal_name == "error_cascade"
