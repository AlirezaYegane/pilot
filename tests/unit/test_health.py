from __future__ import annotations

from types import SimpleNamespace

import pytest

from pilot_core.constants import SessionState, SignalName
from pilot_core.health import (
    SignalHealthInput,
    compute_health_score,
    derive_state_from_health,
    health_score_summary,
    normalise_health_input,
)


def test_derive_state_from_health_uses_expected_bands() -> None:
    assert derive_state_from_health(0.95) is SessionState.HEALTHY
    assert derive_state_from_health(0.75) is SessionState.WATCHING
    assert derive_state_from_health(0.50) is SessionState.DEGRADING
    assert derive_state_from_health(0.20) is SessionState.CRITICAL


def test_empty_signal_results_are_healthy() -> None:
    result = compute_health_score([])

    assert result.health_score == 1.0
    assert result.adjusted_badness_score == 0.0
    assert result.derived_state is SessionState.HEALTHY
    assert result.fired_count == 0
    assert result.observed_signal_count == 0


def test_single_signal_uses_default_weight() -> None:
    result = compute_health_score(
        [
            SignalHealthInput(
                signal_name=SignalName.TOKEN_BURN,
                score=1.0,
                confidence=1.0,
                fired=True,
            )
        ]
    )

    assert result.raw_badness_score == pytest.approx(0.15)
    assert result.adjusted_badness_score == pytest.approx(0.15)
    assert result.health_score == pytest.approx(0.85)
    assert result.derived_state is SessionState.HEALTHY


def test_multiple_fired_signals_apply_penalty() -> None:
    result = compute_health_score(
        [
            SignalHealthInput(SignalName.REPEATED_CALLS, score=1.0, fired=True),
            SignalHealthInput(SignalName.ERROR_CASCADE, score=1.0, fired=True),
            SignalHealthInput(SignalName.RATE_LIMIT, score=1.0, fired=True),
        ]
    )

    assert result.fired_count == 3
    assert result.penalty_multiplier == pytest.approx(1.30)
    assert result.raw_badness_score == pytest.approx(0.65)
    assert result.adjusted_badness_score == pytest.approx(0.845)
    assert result.health_score == pytest.approx(0.155)
    assert result.derived_state is SessionState.CRITICAL
    assert result.should_escalate is True


def test_normalise_health_input_accepts_signal_result_objects() -> None:
    raw = SimpleNamespace(
        signal_name=SignalName.ERROR_CASCADE,
        score=0.7,
        confidence=0.9,
        fired=True,
    )

    item = normalise_health_input(raw)

    assert item.signal_name is SignalName.ERROR_CASCADE
    assert item.score == pytest.approx(0.7)
    assert item.confidence == pytest.approx(0.9)
    assert item.fired is True


def test_normalise_health_input_accepts_dict_with_string_signal_name() -> None:
    item = normalise_health_input(
        {
            "signal_name": "rate_limit",
            "score": "0.85",
            "confidence": "0.8",
        }
    )

    assert item.signal_name is SignalName.RATE_LIMIT
    assert item.score == pytest.approx(0.85)
    assert item.confidence == pytest.approx(0.8)
    assert item.fired is True


def test_mapping_scores_are_supported() -> None:
    result = compute_health_score(
        {
            SignalName.TOKEN_BURN: 1.0,
            "error_cascade": 0.5,
        }
    )

    assert result.observed_signal_count == 2
    assert result.health_score < 1.0


def test_top_contributors_are_sorted_by_weighted_badness() -> None:
    result = compute_health_score(
        [
            SignalHealthInput(SignalName.SELF_DOUBT, score=1.0, fired=True),
            SignalHealthInput(SignalName.RATE_LIMIT, score=0.8, fired=True),
            SignalHealthInput(SignalName.BACKTRACKING, score=0.5, fired=False),
        ]
    )

    top = result.top_contributors

    assert top[0].signal_name is SignalName.RATE_LIMIT
    assert top[0].weighted_badness >= top[1].weighted_badness


def test_health_summary_is_json_serialisable_shape() -> None:
    result = compute_health_score(
        [
            SignalHealthInput(SignalName.RATE_LIMIT, score=1.0, fired=True),
        ]
    )

    summary = health_score_summary(result)

    assert summary["derived_state"] == "watching"
    assert summary["observed_signal_count"] == 1
    assert isinstance(summary["top_contributors"], list)


def test_invalid_signal_name_raises_helpful_error() -> None:
    with pytest.raises(ValueError, match="Invalid signal name"):
        normalise_health_input({"signal_name": "not_a_signal", "score": 1.0})
