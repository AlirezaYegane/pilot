from __future__ import annotations

from types import SimpleNamespace

import pytest

from pilot_core.constants import Severity, SignalName
from pilot_core.signals.rate_limit import (
    DEFAULT_PLAN_NAME,
    PLAN_TOKEN_CAPS,
    RateLimitSignal,
    TokenUsageEvent,
    calibrate_rate_limit_score,
    estimate_used_tokens,
    evaluate_rate_limit,
    normalise_token_usage_event,
    project_eta_minutes,
    recent_usage_events,
    resolve_plan_token_cap,
    token_rate_per_minute,
)


def test_token_usage_event_clamps_negative_total_tokens() -> None:
    event = TokenUsageEvent(total_tokens=-10)

    assert event.event_tokens == 0


def test_normalise_token_usage_event_accepts_dataclass() -> None:
    event = TokenUsageEvent(total_tokens=100, timestamp_ms=123)

    assert normalise_token_usage_event(event) == event


def test_normalise_token_usage_event_accepts_total_tokens_dict() -> None:
    event = normalise_token_usage_event(
        {
            "total_tokens": 250,
            "timestamp_ms": 123,
            "model_name": "claude-sonnet-4",
        }
    )

    assert event.total_tokens == 250
    assert event.timestamp_ms == 123
    assert event.model_name == "claude-sonnet-4"


def test_normalise_token_usage_event_accepts_input_output_tokens() -> None:
    event = normalise_token_usage_event(
        {
            "input_tokens": 100,
            "output_tokens": 75,
            "timestamp_ms": 456,
        }
    )

    assert event.total_tokens == 175
    assert event.input_tokens == 100
    assert event.output_tokens == 75
    assert event.timestamp_ms == 456


def test_normalise_token_usage_event_accepts_estimated_token_keys() -> None:
    event = normalise_token_usage_event(
        {
            "input_tokens_est": 80,
            "output_tokens_est": 20,
        }
    )

    assert event.total_tokens == 100


def test_normalise_token_usage_event_accepts_objects() -> None:
    raw = SimpleNamespace(
        total_tokens=500,
        timestamp_ms=789,
        model_name="claude-opus-4",
    )

    event = normalise_token_usage_event(raw)

    assert event.total_tokens == 500
    assert event.timestamp_ms == 789
    assert event.model_name == "claude-opus-4"


def test_resolve_plan_token_cap_uses_explicit_cap() -> None:
    assert resolve_plan_token_cap(explicit_plan_cap_tokens=123_456) == 123_456


def test_resolve_plan_token_cap_rejects_invalid_explicit_cap() -> None:
    with pytest.raises(ValueError, match="explicit_plan_cap_tokens"):
        resolve_plan_token_cap(explicit_plan_cap_tokens=0)


def test_resolve_plan_token_cap_uses_known_plan() -> None:
    assert resolve_plan_token_cap("pro") == PLAN_TOKEN_CAPS["pro"]
    assert resolve_plan_token_cap("MAX20") == PLAN_TOKEN_CAPS["max20"]


def test_resolve_plan_token_cap_falls_back_to_default_plan() -> None:
    assert resolve_plan_token_cap("unknown") == PLAN_TOKEN_CAPS[DEFAULT_PLAN_NAME]


def test_estimate_used_tokens_prefers_explicit_current_usage() -> None:
    events = (
        TokenUsageEvent(total_tokens=100),
        TokenUsageEvent(total_tokens=200),
    )

    assert estimate_used_tokens(events, current_used_tokens=1_000) == 1_000


def test_estimate_used_tokens_sums_events_when_no_current_usage() -> None:
    events = (
        TokenUsageEvent(total_tokens=100),
        TokenUsageEvent(total_tokens=200),
    )

    assert estimate_used_tokens(events) == 300


def test_recent_usage_events_filters_by_recent_window() -> None:
    events = (
        TokenUsageEvent(total_tokens=100, timestamp_ms=0),
        TokenUsageEvent(total_tokens=100, timestamp_ms=60_000),
        TokenUsageEvent(total_tokens=100, timestamp_ms=600_000),
    )

    recent = recent_usage_events(events, recent_window_minutes=2.0, now_ms=600_000)

    assert recent == (events[2],)


def test_recent_usage_events_rejects_invalid_window() -> None:
    with pytest.raises(ValueError, match="recent_window_minutes"):
        recent_usage_events(tuple(), recent_window_minutes=0.0)


def test_token_rate_per_minute_requires_two_timestamped_events() -> None:
    assert token_rate_per_minute(tuple()) == 0.0
    assert token_rate_per_minute((TokenUsageEvent(total_tokens=100, timestamp_ms=1),)) == 0.0


def test_token_rate_per_minute_calculates_rate() -> None:
    events = (
        TokenUsageEvent(total_tokens=100, timestamp_ms=0),
        TokenUsageEvent(total_tokens=200, timestamp_ms=60_000),
    )

    assert token_rate_per_minute(events) == 300.0


def test_project_eta_minutes_handles_no_rate() -> None:
    assert project_eta_minutes(remaining_tokens=100, rate_tokens_per_minute=0.0) is None


def test_project_eta_minutes_returns_zero_when_quota_is_exhausted() -> None:
    assert project_eta_minutes(remaining_tokens=0, rate_tokens_per_minute=100.0) == 0.0


def test_project_eta_minutes_calculates_eta() -> None:
    assert project_eta_minutes(remaining_tokens=1_000, rate_tokens_per_minute=100.0) == 10.0


def test_calibrate_rate_limit_score_returns_zero_for_unknown_eta() -> None:
    assert calibrate_rate_limit_score(None) == 0.0


def test_calibrate_rate_limit_score_is_critical_for_exhausted_quota() -> None:
    assert calibrate_rate_limit_score(0.0) == 1.0


def test_calibrate_rate_limit_score_warns_under_threshold() -> None:
    assert calibrate_rate_limit_score(15.0, eta_threshold_minutes=20.0) == 0.85


def test_calibrate_rate_limit_score_is_partial_near_threshold() -> None:
    assert calibrate_rate_limit_score(30.0, eta_threshold_minutes=20.0) == 0.5


def test_calibrate_rate_limit_score_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="eta_threshold_minutes"):
        calibrate_rate_limit_score(10.0, eta_threshold_minutes=0.0)


def test_evaluate_rate_limit_waits_for_recent_timestamped_events() -> None:
    result = evaluate_rate_limit(
        [
            {"total_tokens": 100},
            {"total_tokens": 200},
        ],
        explicit_plan_cap_tokens=1_000,
        current_used_tokens=500,
    )

    assert result.signal_name is SignalName.RATE_LIMIT
    assert result.score == 0.0
    assert result.confidence == 0.0
    assert result.severity is Severity.INFO
    assert result.fired is False
    assert "timestamped" in result.explanation


def test_evaluate_rate_limit_fires_when_eta_is_imminent() -> None:
    events = [
        {"total_tokens": 50_000, "timestamp_ms": 0},
        {"total_tokens": 50_000, "timestamp_ms": 60_000},
        {"total_tokens": 50_000, "timestamp_ms": 120_000},
        {"total_tokens": 50_000, "timestamp_ms": 180_000},
        {"total_tokens": 50_000, "timestamp_ms": 240_000},
    ]

    result = evaluate_rate_limit(
        events,
        plan_name="max5",
        current_used_tokens=249_600_000,
        now_ms=240_000,
    )

    assert result.signal_name is SignalName.RATE_LIMIT
    assert result.remaining_tokens == 400_000
    assert result.recent_rate_tokens_per_minute > 0
    assert result.eta_minutes is not None
    assert result.eta_minutes < 20.0
    assert result.score >= 0.85
    assert result.severity in {Severity.WARNING, Severity.CRITICAL}
    assert result.fired is True


def test_evaluate_rate_limit_does_not_fire_when_eta_is_far() -> None:
    events = [
        {"total_tokens": 1_000, "timestamp_ms": 0},
        {"total_tokens": 1_000, "timestamp_ms": 60_000},
        {"total_tokens": 1_000, "timestamp_ms": 120_000},
    ]

    result = evaluate_rate_limit(
        events,
        explicit_plan_cap_tokens=1_000_000,
        current_used_tokens=100_000,
        now_ms=120_000,
    )

    assert result.eta_minutes is not None
    assert result.eta_minutes > 20.0
    assert result.fired is False


def test_rate_limit_signal_wrapper_uses_configuration() -> None:
    signal = RateLimitSignal(
        explicit_plan_cap_tokens=1_000,
        current_used_tokens=950,
        eta_threshold_minutes=20.0,
    )

    result = signal.evaluate(
        [
            {"total_tokens": 25, "timestamp_ms": 0},
            {"total_tokens": 25, "timestamp_ms": 60_000},
        ]
    )

    assert result.signal_name is SignalName.RATE_LIMIT
    assert result.fired is True
