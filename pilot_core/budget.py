"""Budget usage and ETA helpers for Pilot.

Day 51 adds the pure budget layer used later by CLI commands.

This module owns:
- normalising token usage records into budget events
- daily and weekly usage views
- budget usage ratios and remaining token estimates
- rate-limit proximity integration using the existing rate_limit signal

The module is side-effect free:
- it does not read SQLite
- it does not print
- it does not call hooks
- it only converts usage records into serialisable reports
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_DAILY_BUDGET_TOKENS = 10_000_000
DEFAULT_WEEKLY_BUDGET_TOKENS = 50_000_000
DEFAULT_PLAN_CAP_TOKENS = 250_000_000
DEFAULT_PLAN_NAME = "max5"
DEFAULT_RECENT_RATE_WINDOW_MINUTES = 5.0
DEFAULT_RATE_LIMIT_ETA_THRESHOLD_MINUTES = 20.0
DEFAULT_USAGE_WARNING_RATIO = 0.80

MS_PER_MINUTE = 60_000
MS_PER_DAY = 86_400_000


@dataclass(frozen=True)
class BudgetUsageEvent:
    """Normalised token/cost usage event."""

    total_tokens: int
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp_ms: int | None = None
    cost_usd: float = 0.0
    model_name: str | None = None
    source: str = "unknown"

    @property
    def event_tokens(self) -> int:
        """Return non-negative total tokens for this event."""

        if self.total_tokens > 0:
            return self.total_tokens

        return max(0, self.input_tokens) + max(0, self.output_tokens)


@dataclass(frozen=True)
class BudgetWindowSummary:
    """Usage summary for a fixed time window."""

    window_name: str
    start_ms: int
    end_ms: int
    event_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    budget_tokens: int
    usage_ratio: float
    remaining_tokens: int
    warning_ratio: float
    explanation: str

    @property
    def has_budget(self) -> bool:
        """Return True when the window has a positive budget."""

        return self.budget_tokens > 0

    @property
    def is_over_budget(self) -> bool:
        """Return True when usage exceeds the configured budget."""

        return self.has_budget and self.total_tokens > self.budget_tokens

    @property
    def should_warn(self) -> bool:
        """Return True when usage is near or above budget."""

        return self.has_budget and self.usage_ratio >= self.warning_ratio


@dataclass(frozen=True)
class BudgetEtaProjection:
    """Budget ETA derived from the existing rate-limit signal."""

    remaining_tokens: int
    recent_tokens: int
    recent_rate_tokens_per_minute: float
    eta_minutes: float | None
    threshold_minutes: float
    fired: bool
    confidence: float
    explanation: str

    @property
    def eta_text(self) -> str:
        """Return a human-readable ETA."""

        if self.eta_minutes is None:
            return "unknown"

        return f"{self.eta_minutes:.1f} min"


@dataclass(frozen=True)
class BudgetReport:
    """Combined daily/weekly budget usage and ETA report."""

    generated_at_ms: int
    plan_name: str
    plan_cap_tokens: int
    current_used_tokens: int
    daily: BudgetWindowSummary
    weekly: BudgetWindowSummary
    eta: BudgetEtaProjection
    rate_limit_score: float
    rate_limit_fired: bool
    explanation: str

    @property
    def should_warn(self) -> bool:
        """Return True when any budget pressure should be surfaced later."""

        return (
            self.daily.should_warn
            or self.weekly.should_warn
            or self.eta.fired
            or self.rate_limit_fired
        )


def _safe_int(value: object, *, default: int = 0) -> int:
    """Convert value to int safely."""

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int | float):
        return int(value)

    if isinstance(value, str | bytes | bytearray):
        try:
            return int(value)
        except ValueError:
            return default

    return default


def _safe_float(value: object, *, default: float = 0.0) -> float:
    """Convert value to float safely."""

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str | bytes | bytearray):
        try:
            return float(value)
        except ValueError:
            return default

    return default


def _record_get(raw: object, key: str, default: object = None) -> object:
    """Read a value from a mapping-like or object-like record."""

    if isinstance(raw, Mapping):
        return raw.get(key, default)

    return getattr(raw, key, default)


def normalise_budget_usage_event(
    raw: BudgetUsageEvent | Mapping[str, Any] | object,
) -> BudgetUsageEvent:
    """Convert a raw record into a BudgetUsageEvent.

    Supported shapes:
    - {"total_tokens": 100}
    - {"input_tokens": 40, "output_tokens": 60}
    - {"timestamp_ms": 123, "cost_usd": 0.01}
    - object with matching attributes
    """

    if isinstance(raw, BudgetUsageEvent):
        return raw

    total_tokens = _safe_int(_record_get(raw, "total_tokens", 0))
    input_tokens = _safe_int(
        _record_get(raw, "input_tokens", _record_get(raw, "input_tokens_est", 0))
    )
    output_tokens = _safe_int(
        _record_get(raw, "output_tokens", _record_get(raw, "output_tokens_est", 0))
    )

    timestamp_raw = _record_get(raw, "timestamp_ms", None)
    timestamp_ms = _safe_int(timestamp_raw) if timestamp_raw is not None else None

    cost_usd = _safe_float(_record_get(raw, "cost_usd", _record_get(raw, "total_cost_usd", 0.0)))

    model_raw = _record_get(raw, "model_name", _record_get(raw, "model", None))
    source_raw = _record_get(raw, "source", _record_get(raw, "event_type", "unknown"))

    return BudgetUsageEvent(
        total_tokens=max(0, total_tokens),
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
        timestamp_ms=timestamp_ms,
        cost_usd=max(0.0, cost_usd),
        model_name=str(model_raw) if model_raw is not None else None,
        source=str(source_raw) if source_raw is not None else "unknown",
    )


def normalise_budget_usage_events(
    raw_events: Sequence[BudgetUsageEvent | Mapping[str, Any] | object],
) -> tuple[BudgetUsageEvent, ...]:
    """Normalise many usage records."""

    return tuple(normalise_budget_usage_event(event) for event in raw_events)


def resolve_now_ms(
    events: Sequence[BudgetUsageEvent],
    *,
    now_ms: int | None = None,
) -> int:
    """Resolve report generation time."""

    if now_ms is not None:
        return now_ms

    timestamps = tuple(event.timestamp_ms for event in events if event.timestamp_ms is not None)
    if timestamps:
        return max(timestamps)

    return int(time.time() * 1000)


def _local_day_number(timestamp_ms: int, *, timezone_offset_minutes: int = 0) -> int:
    """Return local day number since Unix epoch."""

    shifted_ms = timestamp_ms + timezone_offset_minutes * MS_PER_MINUTE
    return shifted_ms // MS_PER_DAY


def daily_window_ms(
    now_ms: int,
    *,
    timezone_offset_minutes: int = 0,
) -> tuple[int, int]:
    """Return [start, end) for the local day containing now_ms."""

    day_number = _local_day_number(now_ms, timezone_offset_minutes=timezone_offset_minutes)
    start_local_ms = day_number * MS_PER_DAY
    start_ms = start_local_ms - timezone_offset_minutes * MS_PER_MINUTE
    return start_ms, start_ms + MS_PER_DAY


def weekly_window_ms(
    now_ms: int,
    *,
    timezone_offset_minutes: int = 0,
) -> tuple[int, int]:
    """Return [start, end) for the local Monday-based week containing now_ms."""

    day_number = _local_day_number(now_ms, timezone_offset_minutes=timezone_offset_minutes)

    # 1970-01-01 was Thursday. With Monday=0, Thursday=3.
    weekday = (day_number + 3) % 7
    start_day = day_number - weekday

    start_local_ms = start_day * MS_PER_DAY
    start_ms = start_local_ms - timezone_offset_minutes * MS_PER_MINUTE
    return start_ms, start_ms + 7 * MS_PER_DAY


def clamp_ratio(value: float) -> float:
    """Clamp negative ratios while allowing over-budget values above 1.0."""

    return max(0.0, value)


def summarise_budget_window(
    raw_events: Sequence[BudgetUsageEvent | Mapping[str, Any] | object],
    *,
    window_name: str,
    start_ms: int,
    end_ms: int,
    budget_tokens: int = 0,
    warning_ratio: float = DEFAULT_USAGE_WARNING_RATIO,
) -> BudgetWindowSummary:
    """Summarise usage inside a timestamp window."""

    if end_ms <= start_ms:
        raise ValueError("end_ms must be greater than start_ms")

    if budget_tokens < 0:
        raise ValueError("budget_tokens must be greater than or equal to 0")

    if warning_ratio <= 0:
        raise ValueError("warning_ratio must be greater than 0")

    events = normalise_budget_usage_events(raw_events)

    window_events = tuple(
        event
        for event in events
        if event.timestamp_ms is not None and start_ms <= event.timestamp_ms < end_ms
    )

    input_tokens = sum(max(0, event.input_tokens) for event in window_events)
    output_tokens = sum(max(0, event.output_tokens) for event in window_events)
    total_tokens = sum(event.event_tokens for event in window_events)
    cost_usd = sum(event.cost_usd for event in window_events)

    usage_ratio = total_tokens / budget_tokens if budget_tokens > 0 else 0.0
    remaining_tokens = max(0, budget_tokens - total_tokens) if budget_tokens > 0 else 0

    if budget_tokens > 0:
        explanation = (
            f"{window_name} usage is {total_tokens}/{budget_tokens} tokens "
            f"({usage_ratio:.1%}) with {remaining_tokens} remaining."
        )
    else:
        explanation = f"{window_name} usage is {total_tokens} tokens; no budget configured."

    return BudgetWindowSummary(
        window_name=window_name,
        start_ms=start_ms,
        end_ms=end_ms,
        event_count=len(window_events),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        budget_tokens=budget_tokens,
        usage_ratio=clamp_ratio(usage_ratio),
        remaining_tokens=remaining_tokens,
        warning_ratio=warning_ratio,
        explanation=explanation,
    )


def build_daily_usage_view(
    raw_events: Sequence[BudgetUsageEvent | Mapping[str, Any] | object],
    *,
    now_ms: int | None = None,
    daily_budget_tokens: int = DEFAULT_DAILY_BUDGET_TOKENS,
    timezone_offset_minutes: int = 0,
    warning_ratio: float = DEFAULT_USAGE_WARNING_RATIO,
) -> BudgetWindowSummary:
    """Build a daily usage view."""

    events = normalise_budget_usage_events(raw_events)
    resolved_now = resolve_now_ms(events, now_ms=now_ms)
    start_ms, end_ms = daily_window_ms(
        resolved_now,
        timezone_offset_minutes=timezone_offset_minutes,
    )

    return summarise_budget_window(
        events,
        window_name="daily",
        start_ms=start_ms,
        end_ms=end_ms,
        budget_tokens=daily_budget_tokens,
        warning_ratio=warning_ratio,
    )


def build_weekly_usage_view(
    raw_events: Sequence[BudgetUsageEvent | Mapping[str, Any] | object],
    *,
    now_ms: int | None = None,
    weekly_budget_tokens: int = DEFAULT_WEEKLY_BUDGET_TOKENS,
    timezone_offset_minutes: int = 0,
    warning_ratio: float = DEFAULT_USAGE_WARNING_RATIO,
) -> BudgetWindowSummary:
    """Build a weekly usage view."""

    events = normalise_budget_usage_events(raw_events)
    resolved_now = resolve_now_ms(events, now_ms=now_ms)
    start_ms, end_ms = weekly_window_ms(
        resolved_now,
        timezone_offset_minutes=timezone_offset_minutes,
    )

    return summarise_budget_window(
        events,
        window_name="weekly",
        start_ms=start_ms,
        end_ms=end_ms,
        budget_tokens=weekly_budget_tokens,
        warning_ratio=warning_ratio,
    )


def _rate_limit_int(value: object, *, default: int = 0) -> int:
    """Read an integer from a rate-limit result attribute."""

    return _safe_int(value, default=default)


def _rate_limit_float(value: object, *, default: float = 0.0) -> float:
    """Read a float from a rate-limit result attribute."""

    return _safe_float(value, default=default)


def _rate_limit_optional_float(value: object) -> float | None:
    """Read an optional float from a rate-limit result attribute."""

    if value is None:
        return None

    return _safe_float(value)


def build_budget_eta_projection(
    raw_events: Sequence[BudgetUsageEvent | Mapping[str, Any] | object],
    *,
    plan_name: str = DEFAULT_PLAN_NAME,
    plan_cap_tokens: int = DEFAULT_PLAN_CAP_TOKENS,
    current_used_tokens: int | None = None,
    now_ms: int | None = None,
    recent_window_minutes: float = DEFAULT_RECENT_RATE_WINDOW_MINUTES,
    eta_threshold_minutes: float = DEFAULT_RATE_LIMIT_ETA_THRESHOLD_MINUTES,
    min_recent_events: int = 2,
) -> BudgetEtaProjection:
    """Build budget ETA by delegating rate math to the rate-limit signal."""

    from pilot_core.signals.rate_limit import evaluate_rate_limit

    events = normalise_budget_usage_events(raw_events)
    resolved_now = resolve_now_ms(events, now_ms=now_ms)

    if current_used_tokens is None:
        resolved_used_tokens = sum(event.event_tokens for event in events)
    else:
        resolved_used_tokens = max(0, current_used_tokens)

    result = evaluate_rate_limit(
        events,
        plan_name=plan_name,
        explicit_plan_cap_tokens=plan_cap_tokens,
        current_used_tokens=resolved_used_tokens,
        recent_window_minutes=recent_window_minutes,
        eta_threshold_minutes=eta_threshold_minutes,
        min_recent_events=min_recent_events,
        now_ms=resolved_now,
    )

    return BudgetEtaProjection(
        remaining_tokens=_rate_limit_int(getattr(result, "remaining_tokens", 0)),
        recent_tokens=_rate_limit_int(getattr(result, "recent_tokens", 0)),
        recent_rate_tokens_per_minute=_rate_limit_float(
            getattr(result, "recent_rate_tokens_per_minute", 0.0)
        ),
        eta_minutes=_rate_limit_optional_float(getattr(result, "eta_minutes", None)),
        threshold_minutes=eta_threshold_minutes,
        fired=bool(getattr(result, "fired", False)),
        confidence=_rate_limit_float(getattr(result, "confidence", 0.0)),
        explanation=str(getattr(result, "explanation", "")),
    )


def build_budget_report(
    raw_events: Sequence[BudgetUsageEvent | Mapping[str, Any] | object],
    *,
    now_ms: int | None = None,
    plan_name: str = DEFAULT_PLAN_NAME,
    plan_cap_tokens: int = DEFAULT_PLAN_CAP_TOKENS,
    current_used_tokens: int | None = None,
    daily_budget_tokens: int = DEFAULT_DAILY_BUDGET_TOKENS,
    weekly_budget_tokens: int = DEFAULT_WEEKLY_BUDGET_TOKENS,
    timezone_offset_minutes: int = 0,
    recent_window_minutes: float = DEFAULT_RECENT_RATE_WINDOW_MINUTES,
    eta_threshold_minutes: float = DEFAULT_RATE_LIMIT_ETA_THRESHOLD_MINUTES,
    warning_ratio: float = DEFAULT_USAGE_WARNING_RATIO,
) -> BudgetReport:
    """Build the combined budget usage report."""

    from pilot_core.signals.rate_limit import evaluate_rate_limit

    events = normalise_budget_usage_events(raw_events)
    resolved_now = resolve_now_ms(events, now_ms=now_ms)

    if current_used_tokens is None:
        resolved_used_tokens = sum(event.event_tokens for event in events)
    else:
        resolved_used_tokens = max(0, current_used_tokens)

    daily = build_daily_usage_view(
        events,
        now_ms=resolved_now,
        daily_budget_tokens=daily_budget_tokens,
        timezone_offset_minutes=timezone_offset_minutes,
        warning_ratio=warning_ratio,
    )
    weekly = build_weekly_usage_view(
        events,
        now_ms=resolved_now,
        weekly_budget_tokens=weekly_budget_tokens,
        timezone_offset_minutes=timezone_offset_minutes,
        warning_ratio=warning_ratio,
    )

    rate_limit_result = evaluate_rate_limit(
        events,
        plan_name=plan_name,
        explicit_plan_cap_tokens=plan_cap_tokens,
        current_used_tokens=resolved_used_tokens,
        recent_window_minutes=recent_window_minutes,
        eta_threshold_minutes=eta_threshold_minutes,
        now_ms=resolved_now,
    )

    eta = BudgetEtaProjection(
        remaining_tokens=_rate_limit_int(getattr(rate_limit_result, "remaining_tokens", 0)),
        recent_tokens=_rate_limit_int(getattr(rate_limit_result, "recent_tokens", 0)),
        recent_rate_tokens_per_minute=_rate_limit_float(
            getattr(rate_limit_result, "recent_rate_tokens_per_minute", 0.0)
        ),
        eta_minutes=_rate_limit_optional_float(getattr(rate_limit_result, "eta_minutes", None)),
        threshold_minutes=eta_threshold_minutes,
        fired=bool(getattr(rate_limit_result, "fired", False)),
        confidence=_rate_limit_float(getattr(rate_limit_result, "confidence", 0.0)),
        explanation=str(getattr(rate_limit_result, "explanation", "")),
    )

    rate_limit_score = _rate_limit_float(getattr(rate_limit_result, "score", 0.0))
    rate_limit_fired = bool(getattr(rate_limit_result, "fired", False))

    explanation = (
        f"Daily={daily.total_tokens} tokens, weekly={weekly.total_tokens} tokens, "
        f"plan_used={resolved_used_tokens}/{plan_cap_tokens}, eta={eta.eta_text}."
    )

    return BudgetReport(
        generated_at_ms=resolved_now,
        plan_name=plan_name,
        plan_cap_tokens=plan_cap_tokens,
        current_used_tokens=resolved_used_tokens,
        daily=daily,
        weekly=weekly,
        eta=eta,
        rate_limit_score=rate_limit_score,
        rate_limit_fired=rate_limit_fired,
        explanation=explanation,
    )


def budget_window_summary_dict(summary: BudgetWindowSummary) -> dict[str, object]:
    """Return a serialisable budget-window summary."""

    return {
        "window_name": summary.window_name,
        "start_ms": summary.start_ms,
        "end_ms": summary.end_ms,
        "event_count": summary.event_count,
        "input_tokens": summary.input_tokens,
        "output_tokens": summary.output_tokens,
        "total_tokens": summary.total_tokens,
        "cost_usd": round(summary.cost_usd, 6),
        "budget_tokens": summary.budget_tokens,
        "usage_ratio": round(summary.usage_ratio, 6),
        "remaining_tokens": summary.remaining_tokens,
        "should_warn": summary.should_warn,
        "is_over_budget": summary.is_over_budget,
        "explanation": summary.explanation,
    }


def budget_report_summary(report: BudgetReport) -> dict[str, object]:
    """Return a compact serialisable budget report."""

    return {
        "generated_at_ms": report.generated_at_ms,
        "plan_name": report.plan_name,
        "plan_cap_tokens": report.plan_cap_tokens,
        "current_used_tokens": report.current_used_tokens,
        "daily": budget_window_summary_dict(report.daily),
        "weekly": budget_window_summary_dict(report.weekly),
        "eta": {
            "remaining_tokens": report.eta.remaining_tokens,
            "recent_tokens": report.eta.recent_tokens,
            "recent_rate_tokens_per_minute": round(report.eta.recent_rate_tokens_per_minute, 6),
            "eta_minutes": None
            if report.eta.eta_minutes is None
            else round(report.eta.eta_minutes, 6),
            "threshold_minutes": report.eta.threshold_minutes,
            "fired": report.eta.fired,
            "confidence": round(report.eta.confidence, 6),
            "explanation": report.eta.explanation,
        },
        "rate_limit_score": round(report.rate_limit_score, 6),
        "rate_limit_fired": report.rate_limit_fired,
        "should_warn": report.should_warn,
        "explanation": report.explanation,
    }
