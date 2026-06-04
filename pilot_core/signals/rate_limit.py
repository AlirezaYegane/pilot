"""Rate-limit proximity degradation signal.

This signal estimates whether the current token burn trajectory is likely to
exhaust the user's plan quota soon.

Default policy:
- estimate recent token rate from timestamped token usage events
- resolve the plan cap from a known plan name or explicit cap
- project ETA to quota exhaustion
- fire when ETA is below 20 minutes
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pilot_core.constants import Severity, SignalName

DEFAULT_RATE_LIMIT_ETA_THRESHOLD_MINUTES = 20.0
DEFAULT_RECENT_RATE_WINDOW_MINUTES = 5.0
DEFAULT_MIN_RECENT_EVENTS = 2
DEFAULT_PLAN_NAME = "max5"

PLAN_TOKEN_CAPS: dict[str, int] = {
    "pro": 50_000_000,
    "max5": 250_000_000,
    "max20": 1_000_000_000,
}


@dataclass(frozen=True)
class TokenUsageEvent:
    """Minimal token usage event used by rate-limit projection."""

    total_tokens: int
    timestamp_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model_name: str | None = None

    @property
    def event_tokens(self) -> int:
        """Return non-negative total tokens for this event."""

        return max(0, self.total_tokens)


@dataclass(frozen=True)
class RateLimitResult:
    """Result returned by the rate-limit signal."""

    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    observed_event_count: int
    recent_event_count: int
    used_tokens: int
    plan_cap_tokens: int
    remaining_tokens: int
    recent_tokens: int
    recent_rate_tokens_per_minute: float
    eta_minutes: float | None
    eta_threshold_minutes: float
    recent_window_minutes: float
    plan_name: str
    explanation: str

    @property
    def fired(self) -> bool:
        """Return True when projected quota exhaustion is too close."""

        has_enough_events = self.recent_event_count >= DEFAULT_MIN_RECENT_EVENTS
        if self.eta_minutes is None:
            return False
        return has_enough_events and self.eta_minutes < self.eta_threshold_minutes


def clamp_score(value: float) -> float:
    """Clamp a score into the 0..1 range."""

    return max(0.0, min(1.0, value))


def _safe_int(value: object, *, default: int = 0) -> int:
    """Convert value to int without letting bad payloads crash signal logic."""

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


def _record_get(raw: object, key: str, default: object = None) -> object:
    """Read a key from a dict-like or object-like record."""

    if isinstance(raw, Mapping):
        return raw.get(key, default)

    return getattr(raw, key, default)


def normalise_token_usage_event(
    raw: TokenUsageEvent | Mapping[str, Any] | object,
) -> TokenUsageEvent:
    """Convert a dict/object/token record into TokenUsageEvent.

    Supported dict shapes:
    - {"total_tokens": 1000, "timestamp_ms": 123}
    - {"input_tokens": 700, "output_tokens": 300}
    - {"input_tokens_est": 700, "output_tokens_est": 300}
    """

    if isinstance(raw, TokenUsageEvent):
        return raw

    timestamp_value = _record_get(raw, "timestamp_ms", None)
    model_name_value = _record_get(raw, "model_name", _record_get(raw, "model", None))

    total_tokens_value = _record_get(raw, "total_tokens", None)
    if total_tokens_value is not None:
        total_tokens = max(0, _safe_int(total_tokens_value))
        return TokenUsageEvent(
            total_tokens=total_tokens,
            timestamp_ms=_safe_int(timestamp_value) if timestamp_value is not None else None,
            model_name=str(model_name_value) if model_name_value is not None else None,
        )

    input_tokens = _safe_int(
        _record_get(raw, "input_tokens", _record_get(raw, "input_tokens_est", 0))
    )
    output_tokens = _safe_int(
        _record_get(raw, "output_tokens", _record_get(raw, "output_tokens_est", 0))
    )

    return TokenUsageEvent(
        total_tokens=max(0, input_tokens) + max(0, output_tokens),
        timestamp_ms=_safe_int(timestamp_value) if timestamp_value is not None else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_name=str(model_name_value) if model_name_value is not None else None,
    )


def resolve_plan_token_cap(
    plan_name: str = DEFAULT_PLAN_NAME,
    *,
    explicit_plan_cap_tokens: int | None = None,
) -> int:
    """Resolve a quota cap from explicit config or known plan name."""

    if explicit_plan_cap_tokens is not None:
        if explicit_plan_cap_tokens <= 0:
            raise ValueError("explicit_plan_cap_tokens must be greater than 0")
        return explicit_plan_cap_tokens

    normalised_plan = plan_name.lower().strip()
    return PLAN_TOKEN_CAPS.get(normalised_plan, PLAN_TOKEN_CAPS[DEFAULT_PLAN_NAME])


def estimate_used_tokens(
    events: Sequence[TokenUsageEvent],
    *,
    current_used_tokens: int | None = None,
) -> int:
    """Estimate total used tokens from explicit usage or event totals."""

    if current_used_tokens is not None:
        return max(0, current_used_tokens)

    return sum(event.event_tokens for event in events)


def recent_usage_events(
    events: Sequence[TokenUsageEvent],
    *,
    recent_window_minutes: float = DEFAULT_RECENT_RATE_WINDOW_MINUTES,
    now_ms: int | None = None,
) -> tuple[TokenUsageEvent, ...]:
    """Return timestamped events inside the recent rate window."""

    if recent_window_minutes <= 0:
        raise ValueError("recent_window_minutes must be greater than 0")

    timestamped = tuple(event for event in events if event.timestamp_ms is not None)
    if not timestamped:
        return tuple()

    resolved_now = (
        now_ms
        if now_ms is not None
        else max(event.timestamp_ms for event in timestamped if event.timestamp_ms is not None)
    )
    window_ms = int(recent_window_minutes * 60_000)
    window_start = resolved_now - window_ms

    return tuple(
        event
        for event in timestamped
        if event.timestamp_ms is not None and window_start <= event.timestamp_ms <= resolved_now
    )


def token_rate_per_minute(events: Sequence[TokenUsageEvent]) -> float:
    """Estimate tokens/minute from timestamped usage events."""

    timestamped = tuple(event for event in events if event.timestamp_ms is not None)
    if len(timestamped) < 2:
        return 0.0

    timestamps = tuple(
        event.timestamp_ms for event in timestamped if event.timestamp_ms is not None
    )
    min_timestamp = min(timestamps)
    max_timestamp = max(timestamps)

    duration_minutes = (max_timestamp - min_timestamp) / 60_000
    if duration_minutes <= 0:
        return 0.0

    return sum(event.event_tokens for event in timestamped) / duration_minutes


def project_eta_minutes(
    *,
    remaining_tokens: int,
    rate_tokens_per_minute: float,
) -> float | None:
    """Project minutes until quota exhaustion."""

    if remaining_tokens <= 0:
        return 0.0

    if rate_tokens_per_minute <= 0:
        return None

    return remaining_tokens / rate_tokens_per_minute


def calibrate_rate_limit_score(
    eta_minutes: float | None,
    *,
    eta_threshold_minutes: float = DEFAULT_RATE_LIMIT_ETA_THRESHOLD_MINUTES,
) -> float:
    """Convert ETA to a normalized badness score."""

    if eta_threshold_minutes <= 0:
        raise ValueError("eta_threshold_minutes must be greater than 0")

    if eta_minutes is None:
        return 0.0

    if eta_minutes <= 0:
        return 1.0

    if eta_minutes < eta_threshold_minutes * 0.5:
        return 1.0

    if eta_minutes < eta_threshold_minutes:
        return 0.85

    if eta_minutes < eta_threshold_minutes * 2.0:
        return 0.5

    return 0.0


def rate_limit_severity(score: float, *, has_enough_evidence: bool) -> Severity:
    """Map rate-limit score to severity."""

    if not has_enough_evidence:
        return Severity.INFO
    if score >= 0.90:
        return Severity.CRITICAL
    if score >= 0.60:
        return Severity.WARNING
    return Severity.INFO


def evaluate_rate_limit(
    raw_events: Sequence[TokenUsageEvent | Mapping[str, Any] | object],
    *,
    plan_name: str = DEFAULT_PLAN_NAME,
    explicit_plan_cap_tokens: int | None = None,
    current_used_tokens: int | None = None,
    recent_window_minutes: float = DEFAULT_RECENT_RATE_WINDOW_MINUTES,
    eta_threshold_minutes: float = DEFAULT_RATE_LIMIT_ETA_THRESHOLD_MINUTES,
    min_recent_events: int = DEFAULT_MIN_RECENT_EVENTS,
    now_ms: int | None = None,
) -> RateLimitResult:
    """Evaluate rate-limit proximity for recent token usage."""

    if min_recent_events <= 0:
        raise ValueError("min_recent_events must be greater than 0")

    events = [normalise_token_usage_event(item) for item in raw_events]
    cap = resolve_plan_token_cap(
        plan_name,
        explicit_plan_cap_tokens=explicit_plan_cap_tokens,
    )
    used_tokens = estimate_used_tokens(events, current_used_tokens=current_used_tokens)
    remaining_tokens = max(0, cap - used_tokens)

    recent_events = recent_usage_events(
        events,
        recent_window_minutes=recent_window_minutes,
        now_ms=now_ms,
    )
    recent_tokens = sum(event.event_tokens for event in recent_events)
    rate = token_rate_per_minute(recent_events)
    eta = project_eta_minutes(
        remaining_tokens=remaining_tokens,
        rate_tokens_per_minute=rate,
    )

    has_enough_evidence = len(recent_events) >= min_recent_events

    if not has_enough_evidence:
        score = 0.0
        confidence = len(recent_events) / min_recent_events
        explanation = (
            f"Only {len(recent_events)} recent timestamped token event(s) observed; "
            f"need at least {min_recent_events} before projecting rate-limit ETA."
        )
    else:
        score = calibrate_rate_limit_score(
            eta,
            eta_threshold_minutes=eta_threshold_minutes,
        )
        confidence = 1.0
        eta_text = "unknown" if eta is None else f"{eta:.1f} min"
        explanation = (
            f"Used {used_tokens}/{cap} plan tokens with {remaining_tokens} remaining. "
            f"Recent burn rate is {rate:.1f} tokens/min over "
            f"{recent_window_minutes:.1f} min; projected ETA is {eta_text} "
            f"(threshold<{eta_threshold_minutes:.1f} min)."
        )

    return RateLimitResult(
        signal_name=SignalName.RATE_LIMIT,
        score=clamp_score(score),
        confidence=clamp_score(confidence),
        severity=rate_limit_severity(score, has_enough_evidence=has_enough_evidence),
        observed_event_count=len(events),
        recent_event_count=len(recent_events),
        used_tokens=used_tokens,
        plan_cap_tokens=cap,
        remaining_tokens=remaining_tokens,
        recent_tokens=recent_tokens,
        recent_rate_tokens_per_minute=rate,
        eta_minutes=eta,
        eta_threshold_minutes=eta_threshold_minutes,
        recent_window_minutes=recent_window_minutes,
        plan_name=plan_name,
        explanation=explanation,
    )


class RateLimitSignal:
    """Object-oriented wrapper for the rate-limit signal."""

    name = SignalName.RATE_LIMIT

    def __init__(
        self,
        *,
        plan_name: str = DEFAULT_PLAN_NAME,
        explicit_plan_cap_tokens: int | None = None,
        current_used_tokens: int | None = None,
        recent_window_minutes: float = DEFAULT_RECENT_RATE_WINDOW_MINUTES,
        eta_threshold_minutes: float = DEFAULT_RATE_LIMIT_ETA_THRESHOLD_MINUTES,
        min_recent_events: int = DEFAULT_MIN_RECENT_EVENTS,
    ) -> None:
        self.plan_name = plan_name
        self.explicit_plan_cap_tokens = explicit_plan_cap_tokens
        self.current_used_tokens = current_used_tokens
        self.recent_window_minutes = recent_window_minutes
        self.eta_threshold_minutes = eta_threshold_minutes
        self.min_recent_events = min_recent_events

    def evaluate(
        self,
        raw_events: Sequence[TokenUsageEvent | Mapping[str, Any] | object],
    ) -> RateLimitResult:
        """Evaluate this signal against recent token usage events."""

        return evaluate_rate_limit(
            raw_events,
            plan_name=self.plan_name,
            explicit_plan_cap_tokens=self.explicit_plan_cap_tokens,
            current_used_tokens=self.current_used_tokens,
            recent_window_minutes=self.recent_window_minutes,
            eta_threshold_minutes=self.eta_threshold_minutes,
            min_recent_events=self.min_recent_events,
        )
