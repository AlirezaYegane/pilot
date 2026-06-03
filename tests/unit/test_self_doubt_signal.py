from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pilot_core.constants import Severity, SignalName
from pilot_core.signals.self_doubt import (
    AssistantMessage,
    SelfDoubtSignal,
    calibrate_self_doubt_score,
    evaluate_self_doubt,
    extract_assistant_text,
    find_self_doubt_markers,
    normalise_assistant_message,
    recent_assistant_messages,
)

FIXTURE_DIR = Path("tests") / "fixtures"


def test_extract_assistant_text_reads_plain_text_key() -> None:
    assert extract_assistant_text({"text": "Let me try again."}) == "Let me try again."


def test_extract_assistant_text_reads_content_list() -> None:
    raw = {
        "content": [
            {"type": "text", "text": "I see the issue now."},
            {"type": "text", "text": "I will fix it."},
        ]
    }

    assert extract_assistant_text(raw) == "I see the issue now.\nI will fix it."


def test_extract_assistant_text_reads_tool_response_fallback() -> None:
    raw = {"tool_response": {"text": "That did not work."}}

    assert extract_assistant_text(raw) == "That did not work."


def test_normalise_assistant_message_accepts_dataclass() -> None:
    message = AssistantMessage(text="I was wrong.", turn_index=2)

    assert normalise_assistant_message(message) == message


def test_normalise_assistant_message_accepts_dict() -> None:
    message = normalise_assistant_message(
        {
            "text": "My mistake, I missed the import.",
            "turn_index": 3,
            "timestamp_ms": 123,
        }
    )

    assert message.text == "My mistake, I missed the import."
    assert message.turn_index == 3
    assert message.timestamp_ms == 123


def test_normalise_assistant_message_accepts_objects() -> None:
    raw = SimpleNamespace(
        response="This didn't work. I need to rethink.",
        turn_index=4,
        timestamp_ms=456,
    )

    message = normalise_assistant_message(raw)

    assert message.text == "This didn't work. I need to rethink."
    assert message.turn_index == 4
    assert message.timestamp_ms == 456


def test_recent_assistant_messages_uses_latest_window() -> None:
    messages = tuple(AssistantMessage(text=f"message {index}") for index in range(10))

    recent = recent_assistant_messages(messages, window_size=3)

    assert [message.text for message in recent] == ["message 7", "message 8", "message 9"]


def test_recent_assistant_messages_rejects_invalid_window() -> None:
    with pytest.raises(ValueError, match="window_size"):
        recent_assistant_messages(tuple(), window_size=0)


def test_find_self_doubt_markers_detects_default_phrases() -> None:
    messages = (
        AssistantMessage(text="Let me try again."),
        AssistantMessage(text="I see the issue now."),
        AssistantMessage(text="I was wrong."),
    )

    markers = find_self_doubt_markers(messages)

    assert len(markers) == 3
    assert {marker.phrase.lower() for marker in markers} == {
        "let me try again",
        "i see the issue now",
        "i was wrong",
    }


def test_find_self_doubt_markers_ignores_normal_progress_text() -> None:
    messages = (
        AssistantMessage(text="I will implement the parser now."),
        AssistantMessage(text="The tests are passing."),
    )

    assert find_self_doubt_markers(messages) == tuple()


def test_calibrate_self_doubt_score_returns_zero_for_no_markers() -> None:
    assert calibrate_self_doubt_score(0) == 0.0


def test_calibrate_self_doubt_score_returns_partial_score_below_threshold() -> None:
    assert calibrate_self_doubt_score(2) == 0.4


def test_calibrate_self_doubt_score_returns_warning_score_at_threshold() -> None:
    assert calibrate_self_doubt_score(3) == 0.7


def test_calibrate_self_doubt_score_returns_critical_score_above_threshold() -> None:
    assert calibrate_self_doubt_score(4) == 0.95


def test_calibrate_self_doubt_score_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        calibrate_self_doubt_score(1, threshold=0)


def test_evaluate_self_doubt_stays_quiet_for_no_markers() -> None:
    result = evaluate_self_doubt(
        [
            {"text": "I will update the tests."},
            {"text": "Now I will run pytest."},
        ]
    )

    assert result.signal_name is SignalName.SELF_DOUBT
    assert result.score == 0.0
    assert result.severity is Severity.INFO
    assert result.marker_count == 0
    assert not result.fired


def test_evaluate_self_doubt_fires_at_threshold() -> None:
    result = evaluate_self_doubt(
        [
            {"text": "Let me try again."},
            {"text": "I see the issue now."},
            {"text": "I was wrong about the fixture."},
        ]
    )

    assert result.signal_name is SignalName.SELF_DOUBT
    assert result.marker_count == 3
    assert result.score == 0.7
    assert result.severity is Severity.WARNING
    assert result.fired
    assert "threshold>=3" in result.explanation


def test_evaluate_self_doubt_becomes_critical_above_threshold() -> None:
    result = evaluate_self_doubt(
        [
            {"text": "Let me try again."},
            {"text": "I see the issue now."},
            {"text": "I was wrong."},
            {"text": "That did not work. I need to rethink."},
        ]
    )

    assert result.marker_count >= 4
    assert result.score == 0.95
    assert result.severity is Severity.CRITICAL
    assert result.fired


def test_evaluate_self_doubt_uses_recent_window_only() -> None:
    result = evaluate_self_doubt(
        [
            {"text": "Let me try again."},
            {"text": "I see the issue now."},
            {"text": "I was wrong."},
            {"text": "Normal progress."},
            {"text": "Still normal."},
        ],
        window_size=2,
    )

    assert result.marker_count == 0
    assert not result.fired


def test_self_doubt_signal_wrapper_uses_constructor_options() -> None:
    signal = SelfDoubtSignal(threshold=2)

    result = signal.evaluate(
        [
            {"text": "Let me try again."},
            {"text": "I see the issue now."},
        ]
    )

    assert result.marker_count == 2
    assert result.fired


def test_self_doubt_fixture_replays() -> None:
    records = [
        json.loads(line)
        for line in (FIXTURE_DIR / "self_doubt.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    result = evaluate_self_doubt(records)

    assert result.signal_name is SignalName.SELF_DOUBT
    assert result.marker_count >= 3
    assert result.score > 0.0
    assert result.fired
