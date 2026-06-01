from __future__ import annotations

from types import SimpleNamespace

import pytest

from pilot_core.constants import Severity, SignalName
from pilot_core.signals.error_cascade import (
    DEFAULT_ERROR_CASCADE_THRESHOLD,
    DEFAULT_ERROR_CASCADE_WINDOW,
    ErrorCascadeSignal,
    ToolOutcome,
    calibrate_error_cascade_score,
    evaluate_error_cascade,
    failure_rate,
    normalise_tool_outcome,
    recent_outcomes,
)


def test_normalise_tool_outcome_accepts_dataclass() -> None:
    outcome = ToolOutcome(success=True, tool_name="Bash", timestamp_ms=123)

    assert normalise_tool_outcome(outcome) == outcome


def test_normalise_tool_outcome_accepts_dict_with_success() -> None:
    outcome = normalise_tool_outcome(
        {
            "success": False,
            "tool_name": "Bash",
            "timestamp_ms": 123,
        }
    )

    assert outcome.success is False
    assert outcome.tool_name == "Bash"
    assert outcome.timestamp_ms == 123


def test_normalise_tool_outcome_treats_error_dict_as_failure() -> None:
    outcome = normalise_tool_outcome(
        {
            "tool_name": "Read",
            "error": {"type": "RuntimeError", "message": "boom"},
        }
    )

    assert outcome.success is False
    assert outcome.tool_name == "Read"


def test_normalise_tool_outcome_accepts_objects() -> None:
    raw = SimpleNamespace(success=True, tool_name="Edit", timestamp_ms=456)

    outcome = normalise_tool_outcome(raw)

    assert outcome.success is True
    assert outcome.tool_name == "Edit"
    assert outcome.timestamp_ms == 456


def test_recent_outcomes_uses_latest_window() -> None:
    outcomes = tuple(ToolOutcome(success=bool(index % 2)) for index in range(10))

    recent = recent_outcomes(outcomes, window_size=5)

    assert len(recent) == 5
    assert recent == outcomes[-5:]


def test_recent_outcomes_rejects_invalid_window_size() -> None:
    with pytest.raises(ValueError, match="window_size"):
        recent_outcomes(tuple(), window_size=0)


def test_failure_rate_returns_zero_for_empty_window() -> None:
    assert failure_rate(tuple()) == 0.0


def test_failure_rate_counts_failures() -> None:
    outcomes = (
        ToolOutcome(success=True),
        ToolOutcome(success=False),
        ToolOutcome(success=False),
        ToolOutcome(success=True),
    )

    assert failure_rate(outcomes) == 0.5


def test_calibrated_score_maps_threshold_to_one() -> None:
    assert calibrate_error_cascade_score(DEFAULT_ERROR_CASCADE_THRESHOLD) == 1.0


def test_calibrated_score_clamps_high_rates() -> None:
    assert calibrate_error_cascade_score(0.99) == 1.0


def test_calibrated_score_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        calibrate_error_cascade_score(0.5, threshold=0.0)


def test_evaluate_error_cascade_waits_for_minimum_evidence() -> None:
    result = evaluate_error_cascade(
        [
            {"success": False, "tool_name": "Bash"},
            {"success": True, "tool_name": "Read"},
        ]
    )

    assert result.signal_name is SignalName.ERROR_CASCADE
    assert result.score == 0.0
    assert result.confidence < 1.0
    assert result.severity is Severity.INFO
    assert not result.fired
    assert "need at least" in result.explanation


def test_evaluate_error_cascade_stays_quiet_for_healthy_window() -> None:
    result = evaluate_error_cascade(
        [
            {"success": True, "tool_name": "Read"},
            {"success": True, "tool_name": "Edit"},
            {"success": False, "tool_name": "Bash"},
            {"success": True, "tool_name": "Read"},
            {"success": True, "tool_name": "Edit"},
        ]
    )

    assert result.window_size == DEFAULT_ERROR_CASCADE_WINDOW
    assert result.observed_count == 5
    assert result.failure_count == 1
    assert result.failure_rate == 0.2
    assert result.score == 0.5
    assert result.severity is Severity.INFO
    assert not result.fired


def test_evaluate_error_cascade_fires_for_failure_rate_above_threshold() -> None:
    result = evaluate_error_cascade(
        [
            {"success": True, "tool_name": "Read"},
            {"success": False, "tool_name": "Bash"},
            {"success": False, "tool_name": "Bash"},
            {"success": True, "tool_name": "Edit"},
            {"success": False, "tool_name": "Bash"},
        ]
    )

    assert result.observed_count == 5
    assert result.failure_count == 3
    assert result.failure_rate == 0.6
    assert result.score == 1.0
    assert result.severity is Severity.CRITICAL
    assert result.fired
    assert "3/5 recent tool call(s) failed" in result.explanation


def test_evaluate_error_cascade_only_uses_latest_window() -> None:
    result = evaluate_error_cascade(
        [
            {"success": False},
            {"success": False},
            {"success": False},
            {"success": True},
            {"success": True},
            {"success": True},
            {"success": True},
            {"success": True},
        ],
        window_size=5,
    )

    assert result.observed_count == 5
    assert result.failure_count == 0
    assert result.failure_rate == 0.0
    assert result.score == 0.0
    assert not result.fired


def test_error_cascade_signal_wrapper_uses_configured_values() -> None:
    signal = ErrorCascadeSignal(window_size=3, threshold=0.5, min_observations=3)

    result = signal.evaluate(
        [
            {"success": True},
            {"success": False},
            {"success": False},
        ]
    )

    assert signal.name is SignalName.ERROR_CASCADE
    assert result.window_size == 3
    assert result.threshold == 0.5
    assert result.failure_rate == pytest.approx(2 / 3)
    assert result.fired
