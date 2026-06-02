from __future__ import annotations

from types import SimpleNamespace

import pytest

from pilot_core.constants import Defaults, Severity, SignalName
from pilot_core.signals.context_saturation import (
    DEFAULT_CONTEXT_SATURATION_THRESHOLD,
    ContextSaturationSignal,
    TokenEvent,
    calibrate_context_saturation_score,
    context_saturation_ratio,
    estimate_context_tokens,
    evaluate_context_saturation,
    normalise_token_event,
    resolve_model_context_limit,
)


def test_token_event_total_tokens_clamps_negative_values() -> None:
    event = TokenEvent(input_tokens=-10, output_tokens=50)

    assert event.total_tokens == 50


def test_normalise_token_event_accepts_dataclass() -> None:
    event = TokenEvent(input_tokens=100, output_tokens=50)

    assert normalise_token_event(event) == event


def test_normalise_token_event_accepts_dict_with_input_output_tokens() -> None:
    event = normalise_token_event(
        {
            "input_tokens": 100,
            "output_tokens": 75,
            "timestamp_ms": 123,
            "model_name": "claude-sonnet-4",
        }
    )

    assert event.input_tokens == 100
    assert event.output_tokens == 75
    assert event.timestamp_ms == 123
    assert event.model_name == "claude-sonnet-4"
    assert event.total_tokens == 175


def test_normalise_token_event_accepts_estimated_token_keys() -> None:
    event = normalise_token_event(
        {
            "input_tokens_est": 80,
            "output_tokens_est": 20,
        }
    )

    assert event.total_tokens == 100


def test_normalise_token_event_accepts_total_tokens() -> None:
    event = normalise_token_event({"total_tokens": 250})

    assert event.input_tokens == 250
    assert event.output_tokens == 0
    assert event.total_tokens == 250


def test_normalise_token_event_accepts_objects() -> None:
    raw = SimpleNamespace(
        input_tokens=120,
        output_tokens=30,
        timestamp_ms=456,
        model_name="claude-opus-4",
    )

    event = normalise_token_event(raw)

    assert event.total_tokens == 150
    assert event.timestamp_ms == 456
    assert event.model_name == "claude-opus-4"


def test_resolve_model_context_limit_uses_explicit_value() -> None:
    assert resolve_model_context_limit(explicit_context_limit=123_456) == 123_456


def test_resolve_model_context_limit_rejects_invalid_explicit_value() -> None:
    with pytest.raises(ValueError, match="explicit_context_limit"):
        resolve_model_context_limit(explicit_context_limit=0)


def test_resolve_model_context_limit_detects_one_million_models() -> None:
    assert resolve_model_context_limit("claude-sonnet-4-1m") == 1_000_000
    assert resolve_model_context_limit("custom-1000000-context") == 1_000_000


def test_resolve_model_context_limit_falls_back_to_default() -> None:
    assert resolve_model_context_limit(None) == Defaults.DEFAULT_CONTEXT_LIMIT
    assert resolve_model_context_limit("unknown-model") == Defaults.DEFAULT_CONTEXT_LIMIT


def test_estimate_context_tokens_includes_system_prompt_offset() -> None:
    events = (
        TokenEvent(input_tokens=100, output_tokens=50),
        TokenEvent(input_tokens=200, output_tokens=25),
    )

    assert estimate_context_tokens(events, system_prompt_token_offset=1_000) == 1_375


def test_estimate_context_tokens_rejects_negative_offset() -> None:
    with pytest.raises(ValueError, match="system_prompt_token_offset"):
        estimate_context_tokens(tuple(), system_prompt_token_offset=-1)


def test_context_saturation_ratio_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError, match="model_context_limit"):
        context_saturation_ratio(100, 0)


def test_context_saturation_ratio_calculates_ratio() -> None:
    assert context_saturation_ratio(160_000, 200_000) == 0.8


def test_calibrate_context_saturation_score_is_zero_for_low_usage() -> None:
    assert calibrate_context_saturation_score(0.30) == 0.0


def test_calibrate_context_saturation_score_warns_near_threshold() -> None:
    assert calibrate_context_saturation_score(0.75) == 0.6


def test_calibrate_context_saturation_score_is_high_above_threshold() -> None:
    assert calibrate_context_saturation_score(0.85) == 0.8


def test_calibrate_context_saturation_score_is_critical_near_full_context() -> None:
    assert calibrate_context_saturation_score(0.95) == 0.95
    assert calibrate_context_saturation_score(1.05) == 1.0


def test_calibrate_context_saturation_score_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        calibrate_context_saturation_score(0.5, threshold=0.0)


def test_evaluate_context_saturation_waits_for_evidence() -> None:
    result = evaluate_context_saturation([], min_token_events=1)

    assert result.signal_name is SignalName.CONTEXT_SATURATION
    assert result.score == 0.0
    assert result.confidence == 0.0
    assert result.severity is Severity.INFO
    assert not result.fired
    assert "need at least" in result.explanation


def test_evaluate_context_saturation_stays_quiet_for_low_context_usage() -> None:
    result = evaluate_context_saturation(
        [{"total_tokens": 50_000}],
        model_context_limit=200_000,
        system_prompt_token_offset=20_000,
    )

    assert result.context_tokens == 70_000
    assert result.model_context_limit == 200_000
    assert result.saturation_ratio == 0.35
    assert result.score == 0.0
    assert result.severity is Severity.INFO
    assert not result.fired


def test_evaluate_context_saturation_warns_near_threshold_but_does_not_fire() -> None:
    result = evaluate_context_saturation(
        [{"total_tokens": 135_000}],
        model_context_limit=200_000,
        system_prompt_token_offset=20_000,
    )

    assert result.context_tokens == 155_000
    assert result.saturation_ratio == 0.775
    assert result.score == 0.6
    assert result.severity is Severity.WARNING
    assert not result.fired


def test_evaluate_context_saturation_fires_above_threshold() -> None:
    result = evaluate_context_saturation(
        [{"total_tokens": 150_000}],
        model_context_limit=200_000,
        system_prompt_token_offset=20_000,
    )

    assert result.context_tokens == 170_000
    assert result.saturation_ratio == 0.85
    assert result.score == 0.8
    assert result.severity is Severity.WARNING
    assert result.fired
    assert "ratio=0.85" in result.explanation


def test_evaluate_context_saturation_is_critical_when_context_is_full() -> None:
    result = evaluate_context_saturation(
        [{"total_tokens": 190_000}],
        model_context_limit=200_000,
        system_prompt_token_offset=20_000,
    )

    assert result.saturation_ratio == 1.05
    assert result.score == 1.0
    assert result.severity is Severity.CRITICAL
    assert result.fired


def test_evaluate_context_saturation_infers_model_name_from_events() -> None:
    result = evaluate_context_saturation(
        [{"total_tokens": 600_000, "model_name": "claude-sonnet-4-1m"}],
        system_prompt_token_offset=20_000,
    )

    assert result.model_name == "claude-sonnet-4-1m"
    assert result.model_context_limit == 1_000_000
    assert result.saturation_ratio == 0.62
    assert not result.fired


def test_context_saturation_signal_wrapper_uses_configured_values() -> None:
    signal = ContextSaturationSignal(
        model_context_limit=100_000,
        system_prompt_token_offset=10_000,
        threshold=0.80,
    )

    result = signal.evaluate([{"total_tokens": 75_000}])

    assert signal.name is SignalName.CONTEXT_SATURATION
    assert result.context_tokens == 85_000
    assert result.model_context_limit == 100_000
    assert result.saturation_ratio == 0.85
    assert result.fired


def test_default_threshold_matches_plan() -> None:
    assert DEFAULT_CONTEXT_SATURATION_THRESHOLD == 0.80
