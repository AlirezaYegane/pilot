from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pilot_core.constants import Severity, SignalName
from pilot_core.signals.low_productivity import (
    DEFAULT_LOW_PRODUCTIVITY_RATIO_THRESHOLD,
    LowProductivitySignal,
    ProductivityEvent,
    aggregate_productivity,
    calibrate_low_productivity_score,
    evaluate_low_productivity,
    normalise_productivity_event,
    productivity_ratio,
)

FIXTURE_DIR = Path("tests") / "fixtures"


def test_productivity_event_effective_lines_prefers_lines_changed() -> None:
    event = ProductivityEvent(lines_changed=5, lines_added=100, lines_deleted=100)

    assert event.effective_lines_changed == 5


def test_productivity_event_effective_lines_falls_back_to_added_deleted() -> None:
    event = ProductivityEvent(lines_added=7, lines_deleted=3)

    assert event.effective_lines_changed == 10


def test_productivity_event_tokens_prefers_total_tokens() -> None:
    event = ProductivityEvent(total_tokens=1000, input_tokens=1, output_tokens=1)

    assert event.tokens_spent == 1000


def test_productivity_event_tokens_falls_back_to_input_output_tokens() -> None:
    event = ProductivityEvent(input_tokens=800, output_tokens=200)

    assert event.tokens_spent == 1000


def test_normalise_productivity_event_accepts_dataclass() -> None:
    event = ProductivityEvent(session_id="s1", lines_changed=10, total_tokens=1000)

    assert normalise_productivity_event(event) == event


def test_normalise_productivity_event_accepts_dict_with_lines_changed() -> None:
    event = normalise_productivity_event(
        {
            "session_id": "current",
            "turn_index": 2,
            "lines_changed": 10,
            "total_tokens": 1000,
            "timestamp_ms": 123,
        }
    )

    assert event.session_id == "current"
    assert event.turn_index == 2
    assert event.effective_lines_changed == 10
    assert event.tokens_spent == 1000
    assert event.timestamp_ms == 123


def test_normalise_productivity_event_accepts_insertions_deletions_aliases() -> None:
    event = normalise_productivity_event(
        {
            "insertions": 8,
            "deletions": 2,
            "input_tokens_est": 700,
            "output_tokens_est": 300,
        }
    )

    assert event.effective_lines_changed == 10
    assert event.tokens_spent == 1000


def test_normalise_productivity_event_accepts_objects() -> None:
    raw = SimpleNamespace(lines_added=4, lines_deleted=6, input_tokens=900, output_tokens=100)

    event = normalise_productivity_event(raw)

    assert event.effective_lines_changed == 10
    assert event.tokens_spent == 1000


def test_aggregate_productivity_sums_lines_and_tokens() -> None:
    stats = aggregate_productivity(
        [
            ProductivityEvent(lines_changed=10, total_tokens=1000),
            ProductivityEvent(lines_added=5, lines_deleted=5, input_tokens=500, output_tokens=500),
        ]
    )

    assert stats.event_count == 2
    assert stats.lines_changed == 20
    assert stats.tokens_spent == 2000
    assert stats.lines_per_1k_tokens == pytest.approx(10.0)


def test_productivity_ratio_returns_current_over_baseline() -> None:
    ratio = productivity_ratio(current_lines_per_token=0.002, baseline_lines_per_token=0.010)

    assert ratio == pytest.approx(0.2)


def test_productivity_ratio_returns_none_for_empty_baseline() -> None:
    assert productivity_ratio(current_lines_per_token=0.002, baseline_lines_per_token=0.0) is None


def test_calibrate_low_productivity_score() -> None:
    cases: list[tuple[float | None, float]] = [
        (0.60, 0.0),
        (0.45, 0.4),
        (0.30, 0.7),
        (0.10, 0.95),
        (None, 0.0),
    ]

    for ratio, expected_score in cases:
        assert calibrate_low_productivity_score(ratio) == expected_score


def test_evaluate_low_productivity_does_not_fire_when_current_matches_baseline() -> None:
    result = evaluate_low_productivity(
        [{"lines_changed": 10, "total_tokens": 1000}],
        [{"lines_changed": 10, "total_tokens": 1000}],
    )

    assert result.signal_name is SignalName.LOW_PRODUCTIVITY
    assert result.fired is False
    assert result.score == 0.0
    assert result.productivity_ratio == pytest.approx(1.0)
    assert result.severity is Severity.INFO


def test_evaluate_low_productivity_fires_when_current_is_below_half_baseline() -> None:
    result = evaluate_low_productivity(
        [{"lines_changed": 1, "total_tokens": 1000}],
        [{"lines_changed": 10, "total_tokens": 1000}],
    )

    assert result.fired is True
    assert result.score == 0.95
    assert result.productivity_ratio == pytest.approx(0.1)
    assert result.severity is Severity.CRITICAL
    assert "Current productivity" in result.explanation


def test_evaluate_low_productivity_equal_to_threshold_does_not_fire() -> None:
    result = evaluate_low_productivity(
        [{"lines_changed": 5, "total_tokens": 1000}],
        [{"lines_changed": 10, "total_tokens": 1000}],
    )

    assert result.productivity_ratio == pytest.approx(DEFAULT_LOW_PRODUCTIVITY_RATIO_THRESHOLD)
    assert result.fired is False


def test_evaluate_low_productivity_supports_explicit_baseline_ratio() -> None:
    result = evaluate_low_productivity(
        [{"lines_changed": 1, "total_tokens": 1000}],
        baseline_lines_per_token=0.010,
    )

    assert result.fired is True
    assert result.baseline_lines_per_1k_tokens == pytest.approx(10.0)


def test_evaluate_low_productivity_needs_baseline() -> None:
    result = evaluate_low_productivity(
        [{"lines_changed": 1, "total_tokens": 1000}],
    )

    assert result.fired is False
    assert result.score == 0.0
    assert result.confidence == 0.0
    assert "baseline" in result.explanation


def test_evaluate_low_productivity_needs_current_tokens() -> None:
    result = evaluate_low_productivity(
        [{"lines_changed": 1, "total_tokens": 0}],
        [{"lines_changed": 10, "total_tokens": 1000}],
    )

    assert result.fired is False
    assert result.score == 0.0


def test_low_productivity_signal_wrapper_uses_configured_baseline() -> None:
    signal = LowProductivitySignal(
        baseline_events=[{"lines_changed": 10, "total_tokens": 1000}],
    )

    result = signal.evaluate([{"lines_changed": 1, "total_tokens": 1000}])

    assert result.fired is True


def test_low_productivity_fixture_replays() -> None:
    records = [
        json.loads(line)
        for line in (FIXTURE_DIR / "low_productivity.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    baseline = [record for record in records if record["phase"] == "baseline"]
    current = [record for record in records if record["phase"] == "current"]

    result = evaluate_low_productivity(current, baseline)

    assert result.signal_name is SignalName.LOW_PRODUCTIVITY
    assert result.fired is True
    assert result.score > 0.0
    assert result.productivity_ratio is not None
    assert result.productivity_ratio < DEFAULT_LOW_PRODUCTIVITY_RATIO_THRESHOLD


def test_evaluate_low_productivity_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        evaluate_low_productivity([], [], threshold=0.0)
