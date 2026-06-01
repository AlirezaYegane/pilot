from __future__ import annotations

from types import SimpleNamespace

import pytest

from pilot_core.constants import Severity, SignalName
from pilot_core.signals.token_burn import (
    DEFAULT_TOKEN_BURN_RATIO_THRESHOLD,
    TokenBurnSignal,
    TurnTokenUsage,
    average_tokens_per_turn,
    calibrate_token_burn_score,
    evaluate_token_burn,
    normalise_turn_token_usage,
    recent_and_baseline_windows,
    token_burn_ratio,
)


def test_turn_token_usage_total_tokens_clamps_negative_values() -> None:
    usage = TurnTokenUsage(turn_index=1, input_tokens=-10, output_tokens=50)

    assert usage.total_tokens == 50


def test_normalise_turn_token_usage_accepts_dataclass() -> None:
    usage = TurnTokenUsage(turn_index=1, input_tokens=100, output_tokens=50)

    assert normalise_turn_token_usage(usage) == usage


def test_normalise_turn_token_usage_accepts_dict_with_input_output_tokens() -> None:
    usage = normalise_turn_token_usage(
        {
            "turn_index": 2,
            "input_tokens": 100,
            "output_tokens": 75,
            "timestamp_ms": 123,
        }
    )

    assert usage.turn_index == 2
    assert usage.input_tokens == 100
    assert usage.output_tokens == 75
    assert usage.timestamp_ms == 123
    assert usage.total_tokens == 175


def test_normalise_turn_token_usage_accepts_estimated_token_keys() -> None:
    usage = normalise_turn_token_usage(
        {
            "turn_index": 3,
            "input_tokens_est": 80,
            "output_tokens_est": 20,
        }
    )

    assert usage.total_tokens == 100


def test_normalise_turn_token_usage_accepts_total_tokens() -> None:
    usage = normalise_turn_token_usage({"turn_index": 4, "total_tokens": 250})

    assert usage.turn_index == 4
    assert usage.input_tokens == 250
    assert usage.output_tokens == 0
    assert usage.total_tokens == 250


def test_normalise_turn_token_usage_accepts_objects() -> None:
    raw = SimpleNamespace(turn_index=5, input_tokens=120, output_tokens=30, timestamp_ms=456)

    usage = normalise_turn_token_usage(raw)

    assert usage.turn_index == 5
    assert usage.total_tokens == 150
    assert usage.timestamp_ms == 456


def test_recent_and_baseline_windows_split_latest_recent_from_previous_baseline() -> None:
    usages = tuple(TurnTokenUsage(turn_index=index, input_tokens=100) for index in range(15))

    recent, baseline = recent_and_baseline_windows(usages, recent_window=3, baseline_window=10)

    assert [item.turn_index for item in recent] == [12, 13, 14]
    assert [item.turn_index for item in baseline] == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]


def test_recent_and_baseline_windows_reject_invalid_windows() -> None:
    with pytest.raises(ValueError, match="recent_window"):
        recent_and_baseline_windows(tuple(), recent_window=0)

    with pytest.raises(ValueError, match="baseline_window"):
        recent_and_baseline_windows(tuple(), baseline_window=0)


def test_average_tokens_per_turn_returns_zero_for_empty_sequence() -> None:
    assert average_tokens_per_turn(tuple()) == 0.0


def test_average_tokens_per_turn_calculates_mean() -> None:
    usages = (
        TurnTokenUsage(turn_index=1, input_tokens=100),
        TurnTokenUsage(turn_index=2, input_tokens=300),
    )

    assert average_tokens_per_turn(usages) == 200.0


def test_token_burn_ratio_handles_zero_baseline() -> None:
    assert token_burn_ratio(0.0, 0.0) == 0.0
    assert token_burn_ratio(100.0, 0.0) == float("inf")


def test_calibrate_token_burn_score_stays_zero_for_normal_usage() -> None:
    assert calibrate_token_burn_score(1.0) == 0.0


def test_calibrate_token_burn_score_warns_before_threshold() -> None:
    assert calibrate_token_burn_score(1.8) == 0.4


def test_calibrate_token_burn_score_is_high_above_threshold() -> None:
    assert calibrate_token_burn_score(2.4) == 0.7


def test_calibrate_token_burn_score_clamps_extreme_ratio() -> None:
    assert calibrate_token_burn_score(5.0) == 0.95
    assert calibrate_token_burn_score(float("inf")) == 1.0


def test_calibrate_token_burn_score_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        calibrate_token_burn_score(2.0, threshold=0.0)


def test_evaluate_token_burn_waits_for_enough_evidence() -> None:
    result = evaluate_token_burn(
        [
            {"turn_index": 1, "total_tokens": 100},
            {"turn_index": 2, "total_tokens": 250},
        ]
    )

    assert result.signal_name is SignalName.TOKEN_BURN
    assert result.score == 0.0
    assert result.confidence < 1.0
    assert result.severity is Severity.INFO
    assert not result.fired
    assert "need at least" in result.explanation


def test_evaluate_token_burn_stays_quiet_for_stable_usage() -> None:
    raw_usages = [{"turn_index": index, "total_tokens": 100} for index in range(13)]

    result = evaluate_token_burn(raw_usages)

    assert result.baseline_turn_count == 10
    assert result.recent_turn_count == 3
    assert result.baseline_average_tokens == 100.0
    assert result.recent_average_tokens == 100.0
    assert result.ratio == 1.0
    assert result.score == 0.0
    assert result.severity is Severity.INFO
    assert not result.fired


def test_evaluate_token_burn_fires_for_recent_spike() -> None:
    raw_usages = [
        *({"turn_index": index, "total_tokens": 100} for index in range(10)),
        {"turn_index": 10, "total_tokens": 250},
        {"turn_index": 11, "total_tokens": 260},
        {"turn_index": 12, "total_tokens": 240},
    ]

    result = evaluate_token_burn(raw_usages)

    assert result.baseline_average_tokens == 100.0
    assert result.recent_average_tokens == 250.0
    assert result.ratio == 2.5
    assert result.score == 0.7
    assert result.severity is Severity.WARNING
    assert result.fired
    assert "ratio=2.50" in result.explanation


def test_evaluate_token_burn_uses_only_previous_baseline_window() -> None:
    raw_usages = [
        *({"turn_index": index, "total_tokens": 500} for index in range(5)),
        *({"turn_index": index, "total_tokens": 100} for index in range(5, 15)),
        {"turn_index": 15, "total_tokens": 250},
        {"turn_index": 16, "total_tokens": 250},
        {"turn_index": 17, "total_tokens": 250},
    ]

    result = evaluate_token_burn(raw_usages)

    assert result.baseline_turn_count == 10
    assert result.baseline_average_tokens == 100.0
    assert result.recent_average_tokens == 250.0
    assert result.fired


def test_token_burn_signal_wrapper_uses_configured_values() -> None:
    signal = TokenBurnSignal(
        recent_window=2,
        baseline_window=3,
        threshold=1.5,
        min_recent_turns=2,
        min_baseline_turns=3,
    )

    result = signal.evaluate(
        [
            {"turn_index": 0, "total_tokens": 100},
            {"turn_index": 1, "total_tokens": 100},
            {"turn_index": 2, "total_tokens": 100},
            {"turn_index": 3, "total_tokens": 200},
            {"turn_index": 4, "total_tokens": 220},
        ]
    )

    assert signal.name is SignalName.TOKEN_BURN
    assert result.threshold == 1.5
    assert result.recent_average_tokens == 210.0
    assert result.baseline_average_tokens == 100.0
    assert result.ratio == pytest.approx(2.1)
    assert result.fired


def test_evaluate_token_burn_rejects_invalid_minimums() -> None:
    with pytest.raises(ValueError, match="min_recent_turns"):
        evaluate_token_burn([], min_recent_turns=0)

    with pytest.raises(ValueError, match="min_baseline_turns"):
        evaluate_token_burn([], min_baseline_turns=0)


def test_default_threshold_matches_plan() -> None:
    assert DEFAULT_TOKEN_BURN_RATIO_THRESHOLD == 2.0
