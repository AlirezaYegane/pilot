from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pilot_core.constants import Severity, SignalName
from pilot_core.signals.backtracking import (
    BacktrackingEvent,
    BacktrackingEventKind,
    BacktrackingSignal,
    calibrate_backtracking_score,
    count_backtracking_edits,
    evaluate_backtracking,
    extract_file_path,
    has_user_feedback_between,
    normalise_backtracking_event,
    normalise_file_path,
)

FIXTURE_DIR = Path("tests") / "fixtures"


def test_normalise_file_path_handles_windows_paths_case_insensitively() -> None:
    assert normalise_file_path(r"SRC\Pilot\Core.py") == "src/pilot/core.py"


def test_normalise_file_path_can_preserve_case() -> None:
    assert normalise_file_path("Src/App.py", case_insensitive=False) == "Src/App.py"


def test_extract_file_path_reads_top_level_path() -> None:
    assert extract_file_path({"file_path": "pilot_core/signals/foo.py"}) == (
        "pilot_core/signals/foo.py"
    )


def test_extract_file_path_reads_nested_tool_input() -> None:
    raw = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "pilot_core/signals/backtracking.py",
        },
    }

    assert extract_file_path(raw) == "pilot_core/signals/backtracking.py"


def test_normalise_backtracking_event_accepts_dataclass() -> None:
    event = BacktrackingEvent(
        kind=BacktrackingEventKind.EDIT,
        turn_index=1,
        file_path="a.py",
    )

    assert normalise_backtracking_event(event) == event


def test_normalise_backtracking_event_detects_edit_tool() -> None:
    event = normalise_backtracking_event(
        {
            "tool_name": "Edit",
            "turn_index": 2,
            "tool_input": {"file_path": "A.py"},
            "timestamp_ms": 123,
        }
    )

    assert event.kind is BacktrackingEventKind.EDIT
    assert event.turn_index == 2
    assert event.file_path == "a.py"
    assert event.tool_name == "Edit"
    assert event.timestamp_ms == 123


def test_normalise_backtracking_event_detects_user_feedback_by_event_type() -> None:
    event = normalise_backtracking_event(
        {
            "event_type": "user_prompt",
            "turn_index": 3,
        }
    )

    assert event.kind is BacktrackingEventKind.USER_FEEDBACK
    assert event.file_path is None


def test_normalise_backtracking_event_detects_user_feedback_by_role() -> None:
    event = normalise_backtracking_event(
        {
            "role": "user",
            "turn_index": 4,
        }
    )

    assert event.kind is BacktrackingEventKind.USER_FEEDBACK


def test_normalise_backtracking_event_accepts_objects() -> None:
    raw = SimpleNamespace(
        tool_name="Write",
        turn_index=5,
        file_path="Pilot_Core/Signals/Backtracking.py",
    )

    event = normalise_backtracking_event(raw)

    assert event.kind is BacktrackingEventKind.EDIT
    assert event.file_path == "pilot_core/signals/backtracking.py"


def test_has_user_feedback_between_detects_feedback_marker() -> None:
    events = (
        BacktrackingEvent(BacktrackingEventKind.EDIT, turn_index=1, file_path="a.py"),
        BacktrackingEvent(BacktrackingEventKind.USER_FEEDBACK, turn_index=2),
        BacktrackingEvent(BacktrackingEventKind.EDIT, turn_index=2, file_path="a.py"),
    )

    assert has_user_feedback_between(events, previous_index=0, current_index=2)


def test_count_backtracking_edits_counts_repeated_file_without_feedback() -> None:
    events = (
        BacktrackingEvent(BacktrackingEventKind.EDIT, turn_index=1, file_path="a.py"),
        BacktrackingEvent(BacktrackingEventKind.OTHER, turn_index=1),
        BacktrackingEvent(BacktrackingEventKind.EDIT, turn_index=2, file_path="a.py"),
        BacktrackingEvent(BacktrackingEventKind.EDIT, turn_index=3, file_path="a.py"),
    )

    count, files = count_backtracking_edits(events, lookback_turns=3)

    assert count == 2
    assert files == ("a.py",)


def test_count_backtracking_edits_ignores_feedback_between_edits() -> None:
    events = (
        BacktrackingEvent(BacktrackingEventKind.EDIT, turn_index=1, file_path="a.py"),
        BacktrackingEvent(BacktrackingEventKind.USER_FEEDBACK, turn_index=2),
        BacktrackingEvent(BacktrackingEventKind.EDIT, turn_index=2, file_path="a.py"),
    )

    count, files = count_backtracking_edits(events, lookback_turns=3)

    assert count == 0
    assert files == tuple()


def test_count_backtracking_edits_respects_lookback_turns() -> None:
    events = (
        BacktrackingEvent(BacktrackingEventKind.EDIT, turn_index=1, file_path="a.py"),
        BacktrackingEvent(BacktrackingEventKind.EDIT, turn_index=10, file_path="a.py"),
    )

    count, files = count_backtracking_edits(events, lookback_turns=3)

    assert count == 0
    assert files == tuple()


def test_count_backtracking_edits_rejects_invalid_lookback() -> None:
    with pytest.raises(ValueError, match="lookback_turns"):
        count_backtracking_edits(tuple(), lookback_turns=0)


def test_calibrate_backtracking_score_is_zero_without_backtracking() -> None:
    assert calibrate_backtracking_score(0) == 0.0


def test_calibrate_backtracking_score_warns_below_threshold() -> None:
    assert calibrate_backtracking_score(1) == 0.4


def test_calibrate_backtracking_score_fires_at_threshold() -> None:
    assert calibrate_backtracking_score(2) == 0.7


def test_calibrate_backtracking_score_is_critical_above_threshold() -> None:
    assert calibrate_backtracking_score(3) == 0.95


def test_calibrate_backtracking_score_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        calibrate_backtracking_score(1, threshold=0)


def test_evaluate_backtracking_waits_for_enough_edit_events() -> None:
    result = evaluate_backtracking(
        [
            {
                "tool_name": "Edit",
                "turn_index": 1,
                "tool_input": {"file_path": "a.py"},
            }
        ]
    )

    assert result.signal_name is SignalName.BACKTRACKING
    assert result.score == 0.0
    assert result.confidence < 1.0
    assert result.severity is Severity.INFO
    assert not result.fired
    assert "need at least" in result.explanation


def test_evaluate_backtracking_stays_quiet_for_different_files() -> None:
    result = evaluate_backtracking(
        [
            {"tool_name": "Edit", "turn_index": 1, "tool_input": {"file_path": "a.py"}},
            {"tool_name": "Edit", "turn_index": 2, "tool_input": {"file_path": "b.py"}},
            {"tool_name": "Edit", "turn_index": 3, "tool_input": {"file_path": "c.py"}},
        ]
    )

    assert result.edit_event_count == 3
    assert result.backtrack_count == 0
    assert result.repeated_files == tuple()
    assert result.score == 0.0
    assert result.severity is Severity.INFO
    assert not result.fired


def test_evaluate_backtracking_stays_quiet_when_user_feedback_breaks_loop() -> None:
    result = evaluate_backtracking(
        [
            {"tool_name": "Edit", "turn_index": 1, "tool_input": {"file_path": "a.py"}},
            {"event_type": "user_prompt", "turn_index": 2},
            {"tool_name": "Edit", "turn_index": 2, "tool_input": {"file_path": "a.py"}},
        ]
    )

    assert result.backtrack_count == 0
    assert not result.fired


def test_evaluate_backtracking_fires_for_repeated_file_edits_without_feedback() -> None:
    result = evaluate_backtracking(
        [
            {"tool_name": "Edit", "turn_index": 1, "tool_input": {"file_path": "a.py"}},
            {"tool_name": "Read", "turn_index": 1},
            {"tool_name": "Edit", "turn_index": 2, "tool_input": {"file_path": "a.py"}},
            {"tool_name": "Edit", "turn_index": 3, "tool_input": {"file_path": "a.py"}},
        ]
    )

    assert result.edit_event_count == 3
    assert result.backtrack_count == 2
    assert result.repeated_files == ("a.py",)
    assert result.score == 0.7
    assert result.severity is Severity.WARNING
    assert result.fired
    assert "without user feedback" in result.explanation


def test_backtracking_signal_wrapper_uses_configured_values() -> None:
    signal = BacktrackingSignal(
        lookback_turns=5,
        threshold=1,
        min_edit_events=2,
    )

    result = signal.evaluate(
        [
            {"tool_name": "Edit", "turn_index": 1, "tool_input": {"file_path": "a.py"}},
            {"tool_name": "Edit", "turn_index": 4, "tool_input": {"file_path": "a.py"}},
        ]
    )

    assert signal.name is SignalName.BACKTRACKING
    assert result.lookback_turns == 5
    assert result.threshold == 1
    assert result.backtrack_count == 1
    assert result.fired


def test_backtracking_fixture_replays() -> None:
    records: list[dict[str, object]] = []

    for line in (FIXTURE_DIR / "backtracking.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        assert isinstance(raw, dict)
        records.append(raw)

    result = evaluate_backtracking(records)

    assert result.signal_name is SignalName.BACKTRACKING
    assert result.score > 0.0
    assert result.backtrack_count >= 2
    assert result.fired
