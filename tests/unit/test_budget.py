from __future__ import annotations

import pytest

from pilot_core.budget import (
    MS_PER_DAY,
    BudgetUsageEvent,
    budget_report_summary,
    build_budget_eta_projection,
    build_budget_report,
    build_daily_usage_view,
    build_weekly_usage_view,
    daily_window_ms,
    normalise_budget_usage_event,
    summarise_budget_window,
    weekly_window_ms,
)


def test_normalise_budget_usage_event_accepts_total_tokens() -> None:
    event = normalise_budget_usage_event(
        {
            "total_tokens": "120",
            "timestamp_ms": "60000",
            "cost_usd": "0.012",
            "model": "claude-sonnet-4",
        }
    )

    assert event.event_tokens == 120
    assert event.timestamp_ms == 60_000
    assert event.cost_usd == 0.012
    assert event.model_name == "claude-sonnet-4"


def test_normalise_budget_usage_event_falls_back_to_input_output_tokens() -> None:
    event = normalise_budget_usage_event(
        {
            "input_tokens": 40,
            "output_tokens": 60,
            "timestamp_ms": 1,
        }
    )

    assert event.total_tokens == 0
    assert event.event_tokens == 100


def test_daily_window_uses_local_timezone_offset() -> None:
    start_ms, end_ms = daily_window_ms(12 * 60 * 60 * 1000, timezone_offset_minutes=0)

    assert start_ms == 0
    assert end_ms == MS_PER_DAY


def test_weekly_window_is_monday_based() -> None:
    # Unix epoch was Thursday 1970-01-01, so the Monday of that week is negative.
    start_ms, end_ms = weekly_window_ms(0, timezone_offset_minutes=0)

    assert start_ms == -3 * MS_PER_DAY
    assert end_ms == 4 * MS_PER_DAY


def test_summarise_budget_window_filters_timestamped_events() -> None:
    summary = summarise_budget_window(
        [
            {"total_tokens": 100, "timestamp_ms": 0, "cost_usd": 0.01},
            {"total_tokens": 200, "timestamp_ms": 1_000, "cost_usd": 0.02},
            {"total_tokens": 999, "timestamp_ms": MS_PER_DAY + 1},
            {"total_tokens": 500},
        ],
        window_name="daily",
        start_ms=0,
        end_ms=MS_PER_DAY,
        budget_tokens=1_000,
    )

    assert summary.event_count == 2
    assert summary.total_tokens == 300
    assert summary.cost_usd == pytest.approx(0.03)
    assert summary.remaining_tokens == 700
    assert summary.usage_ratio == pytest.approx(0.3)
    assert summary.should_warn is False


def test_daily_usage_view_warns_near_budget() -> None:
    summary = build_daily_usage_view(
        [
            {"total_tokens": 800, "timestamp_ms": 0},
            {"total_tokens": 50, "timestamp_ms": 60_000},
        ],
        now_ms=60_000,
        daily_budget_tokens=1_000,
    )

    assert summary.total_tokens == 850
    assert summary.should_warn is True
    assert summary.is_over_budget is False


def test_weekly_usage_view_collects_multiple_days() -> None:
    summary = build_weekly_usage_view(
        [
            {"total_tokens": 100, "timestamp_ms": 0},
            {"total_tokens": 200, "timestamp_ms": MS_PER_DAY},
            {"total_tokens": 300, "timestamp_ms": 8 * MS_PER_DAY},
        ],
        now_ms=MS_PER_DAY,
        weekly_budget_tokens=1_000,
    )

    assert summary.total_tokens == 300
    assert summary.event_count == 2


def test_budget_eta_projection_fires_when_quota_is_close() -> None:
    events = [
        {"total_tokens": 50_000, "timestamp_ms": 0},
        {"total_tokens": 50_000, "timestamp_ms": 60_000},
        {"total_tokens": 50_000, "timestamp_ms": 120_000},
        {"total_tokens": 50_000, "timestamp_ms": 180_000},
        {"total_tokens": 50_000, "timestamp_ms": 240_000},
    ]

    eta = build_budget_eta_projection(
        events,
        plan_cap_tokens=250_000_000,
        current_used_tokens=249_600_000,
        now_ms=240_000,
    )

    assert eta.remaining_tokens == 400_000
    assert eta.eta_minutes is not None
    assert eta.eta_minutes < 20.0
    assert eta.fired is True
    assert eta.confidence == 1.0


def test_budget_report_combines_daily_weekly_and_rate_limit() -> None:
    events = [
        {"total_tokens": 50_000, "timestamp_ms": 0},
        {"total_tokens": 50_000, "timestamp_ms": 60_000},
        {"total_tokens": 50_000, "timestamp_ms": 120_000},
        {"total_tokens": 50_000, "timestamp_ms": 180_000},
        {"total_tokens": 50_000, "timestamp_ms": 240_000},
    ]

    report = build_budget_report(
        events,
        now_ms=240_000,
        plan_cap_tokens=250_000_000,
        current_used_tokens=249_600_000,
        daily_budget_tokens=300_000,
        weekly_budget_tokens=1_000_000,
    )

    assert report.daily.total_tokens == 250_000
    assert report.weekly.total_tokens == 250_000
    assert report.daily.should_warn is True
    assert report.rate_limit_fired is True
    assert report.should_warn is True

    summary = budget_report_summary(report)
    assert summary["should_warn"] is True
    assert isinstance(summary["daily"], dict)


def test_summarise_budget_window_rejects_bad_window() -> None:
    with pytest.raises(ValueError, match="end_ms"):
        summarise_budget_window(
            [BudgetUsageEvent(total_tokens=1)],
            window_name="bad",
            start_ms=10,
            end_ms=10,
        )
