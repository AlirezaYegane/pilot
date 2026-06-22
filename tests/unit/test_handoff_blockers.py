from __future__ import annotations

import pytest

from pilot_core.handoff import HandoffBlockerSeverity
from pilot_core.handoff_blockers import (
    HandoffAttemptEvent,
    extract_handoff_blockers,
    find_failing_loops,
    find_repeated_attempts,
    handoff_blocker_extraction_summary,
    normalise_handoff_attempt_event,
    recent_handoff_attempt_events,
)


def test_normalise_handoff_attempt_event_accepts_success_flag_and_error() -> None:
    event = normalise_handoff_attempt_event(
        {
            "tool_name": "Bash",
            "input_hash": "same-command",
            "success": False,
            "error": {"message": "pytest failed"},
            "turn_index": 7,
        }
    )

    assert event.tool_name == "Bash"
    assert event.attempt_key == "Bash:hash:same-command"
    assert event.failed
    assert event.error_text == "pytest failed"
    assert event.turn_index == 7


def test_normalise_handoff_attempt_event_infers_failure_from_error() -> None:
    event = normalise_handoff_attempt_event(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": "pilot_core/example.py"},
            "error": "file not found",
        }
    )

    assert event.failed
    assert event.tool_name == "Edit"
    assert event.error_text == "file not found"
    assert event.attempt_key.startswith("Edit:input:")


def test_recent_handoff_attempt_events_uses_latest_window() -> None:
    records = [{"tool_name": "Bash", "input_hash": f"cmd-{index}"} for index in range(5)]

    events = recent_handoff_attempt_events(records, window_size=2)

    assert [event.attempt_key for event in events] == [
        "Bash:hash:cmd-3",
        "Bash:hash:cmd-4",
    ]


def test_recent_handoff_attempt_events_rejects_invalid_window() -> None:
    with pytest.raises(ValueError, match="window_size"):
        recent_handoff_attempt_events([], window_size=0)


def test_find_failing_loops_detects_consecutive_same_failed_attempt() -> None:
    events = (
        HandoffAttemptEvent(
            tool_name="Bash",
            attempt_key="Bash:hash:pytest",
            success=False,
            error_text="same failure",
            turn_index=1,
        ),
        HandoffAttemptEvent(
            tool_name="Bash",
            attempt_key="Bash:hash:pytest",
            success=False,
            error_text="same failure",
            turn_index=2,
        ),
        HandoffAttemptEvent(
            tool_name="Bash",
            attempt_key="Bash:hash:pytest",
            success=False,
            error_text="same failure",
            turn_index=3,
        ),
    )

    loops = find_failing_loops(events)

    assert len(loops) == 1
    assert loops[0].tool_name == "Bash"
    assert loops[0].failure_count == 3
    assert loops[0].first_turn_index == 1
    assert loops[0].last_turn_index == 3


def test_find_failing_loops_resets_on_success() -> None:
    events = (
        HandoffAttemptEvent("Bash", "same", success=False),
        HandoffAttemptEvent("Bash", "same", success=False),
        HandoffAttemptEvent("Bash", "same", success=True),
        HandoffAttemptEvent("Bash", "same", success=False),
    )

    assert find_failing_loops(events) == tuple()


def test_find_repeated_attempts_detects_non_consecutive_retries() -> None:
    events = (
        HandoffAttemptEvent("Bash", "same", success=False, error_text="failed once"),
        HandoffAttemptEvent("Read", "other", success=True),
        HandoffAttemptEvent("Bash", "same", success=True),
        HandoffAttemptEvent("Bash", "same", success=False, error_text="failed again"),
    )

    repeated = find_repeated_attempts(events)

    assert len(repeated) == 1
    assert repeated[0].attempt_count == 3
    assert repeated[0].failure_count == 2
    assert repeated[0].has_failures


def test_extract_handoff_blockers_stays_quiet_for_healthy_records() -> None:
    result = extract_handoff_blockers(
        [
            {"tool_name": "Read", "input_hash": "a", "success": True},
            {"tool_name": "Grep", "input_hash": "b", "success": True},
            {"tool_name": "Bash", "input_hash": "c", "success": True},
        ]
    )

    assert result.blockers == tuple()
    assert result.do_not_redo == tuple()
    assert not result.has_blockers


def test_extract_handoff_blockers_returns_schema_blockers_and_do_not_redo() -> None:
    result = extract_handoff_blockers(
        [
            {
                "tool_name": "Bash",
                "input_hash": "pytest-loop",
                "success": False,
                "error": "same pytest failure",
                "turn_index": 1,
            },
            {
                "tool_name": "Bash",
                "input_hash": "pytest-loop",
                "success": False,
                "error": "same pytest failure",
                "turn_index": 2,
            },
            {
                "tool_name": "Bash",
                "input_hash": "pytest-loop",
                "success": False,
                "error": "same pytest failure",
                "turn_index": 3,
            },
        ]
    )

    assert len(result.blockers) >= 1
    assert len(result.do_not_redo) >= 1
    assert result.blockers[0].severity is HandoffBlockerSeverity.ERROR
    assert "Failing loop detected" in result.blockers[0].description
    assert "Do not blindly retry" in result.do_not_redo[0].item


def test_handoff_blocker_extraction_summary_is_serialisable() -> None:
    result = extract_handoff_blockers(
        [
            {"tool_name": "Bash", "input_hash": "same", "success": False},
            {"tool_name": "Bash", "input_hash": "same", "success": False},
            {"tool_name": "Bash", "input_hash": "same", "success": False},
        ]
    )

    summary = handoff_blocker_extraction_summary(result)

    assert summary["blocker_count"] == 2
    assert summary["do_not_redo_count"] == 2
    assert summary["failing_loop_count"] == 1
    assert summary["repeated_attempt_count"] == 1
    assert summary["has_blockers"] is True
