"""Low-productivity degradation signal.

This signal compares recent coding productivity against a previous-session
baseline.

Default policy:
- productivity = lines_changed / tokens_spent
- compare current productivity with baseline productivity
- fire when current productivity is less than 0.5x baseline

This is intentionally conservative. Some tasks are research/debug-heavy and may
change few lines, so the signal starts as a pure detector that can be combined
with other degradation signals later.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Any

from pilot_core.constants import Severity, SignalName

DEFAULT_LOW_PRODUCTIVITY_RATIO_THRESHOLD = 0.50
DEFAULT_MIN_CURRENT_EVENTS = 1
DEFAULT_MIN_BASELINE_EVENTS = 1
DEFAULT_MIN_CURRENT_TOKENS = 1
DEFAULT_MIN_BASELINE_TOKENS = 1


@dataclass(frozen=True)
class ProductivityEvent:
    """Minimal productivity record for one turn, tool call, or session slice."""

    session_id: str | None = None
    turn_index: int | None = None
    lines_changed: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int | None = None
    timestamp_ms: int | None = None

    @property
    def effective_lines_changed(self) -> int:
        """Return non-negative changed lines for this event."""

        if self.lines_changed > 0:
            return self.lines_changed

        return max(0, self.lines_added) + max(0, self.lines_deleted)

    @property
    def tokens_spent(self) -> int:
        """Return non-negative token spend for this event."""

        if self.total_tokens is not None:
            return max(0, self.total_tokens)

        return max(0, self.input_tokens) + max(0, self.output_tokens)


@dataclass(frozen=True)
class ProductivityStats:
    """Aggregated productivity stats."""

    event_count: int
    lines_changed: int
    tokens_spent: int

    @property
    def lines_per_token(self) -> float:
        """Return changed lines per token."""

        if self.tokens_spent <= 0:
            return 0.0

        return self.lines_changed / self.tokens_spent

    @property
    def lines_per_1k_tokens(self) -> float:
        """Return changed lines per 1,000 tokens for readable output."""

        return self.lines_per_token * 1_000


@dataclass(frozen=True)
class LowProductivityResult:
    """Result returned by the low-productivity signal."""

    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    current_event_count: int
    baseline_event_count: int
    current_lines_changed: int
    current_tokens_spent: int
    baseline_lines_changed: int | None
    baseline_tokens_spent: int | None
    current_lines_per_1k_tokens: float
    baseline_lines_per_1k_tokens: float | None
    productivity_ratio: float | None
    threshold: float
    min_current_events: int
    min_baseline_events: int
    min_current_tokens: int
    min_baseline_tokens: int
    explanation: str

    @property
    def fired(self) -> bool:
        """Return True when productivity is materially below baseline."""

        if self.productivity_ratio is None:
            return False

        has_current_evidence = (
            self.current_event_count >= self.min_current_events
            and self.current_tokens_spent >= self.min_current_tokens
        )
        has_baseline_evidence = self.baseline_event_count >= self.min_baseline_events

        if self.baseline_tokens_spent is not None:
            has_baseline_evidence = (
                has_baseline_evidence and self.baseline_tokens_spent >= self.min_baseline_tokens
            )

        return (
            has_current_evidence
            and has_baseline_evidence
            and self.productivity_ratio < self.threshold
        )


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


def _optional_int(value: object) -> int | None:
    """Convert value to int when present."""

    if value is None:
        return None

    return _safe_int(value)


def _record_get(raw: object, key: str, default: object = None) -> object:
    """Read a key from a dict-like or object-like record."""

    if isinstance(raw, Mapping):
        return raw.get(key, default)

    return getattr(raw, key, default)


def normalise_productivity_event(
    raw: ProductivityEvent | Mapping[str, Any] | object,
) -> ProductivityEvent:
    """Convert a dict/object/session record into ProductivityEvent.

    Supported shapes:
    - {"lines_changed": 10, "total_tokens": 1000}
    - {"lines_added": 7, "lines_deleted": 3, "input_tokens": 800, "output_tokens": 200}
    - {"insertions": 7, "deletions": 3, "input_tokens_est": 800, "output_tokens_est": 200}
    """

    if isinstance(raw, ProductivityEvent):
        return raw

    session_id_value = _record_get(raw, "session_id", None)
    turn_index_value = _record_get(raw, "turn_index", None)
    timestamp_value = _record_get(raw, "timestamp_ms", None)

    lines_changed = _safe_int(
        _record_get(
            raw,
            "lines_changed",
            _record_get(raw, "changed_lines", _record_get(raw, "loc_changed", 0)),
        )
    )
    lines_added = _safe_int(
        _record_get(
            raw,
            "lines_added",
            _record_get(raw, "added_lines", _record_get(raw, "insertions", 0)),
        )
    )
    lines_deleted = _safe_int(
        _record_get(
            raw,
            "lines_deleted",
            _record_get(raw, "deleted_lines", _record_get(raw, "deletions", 0)),
        )
    )

    total_tokens = _optional_int(_record_get(raw, "total_tokens", None))
    input_tokens = _safe_int(
        _record_get(raw, "input_tokens", _record_get(raw, "input_tokens_est", 0))
    )
    output_tokens = _safe_int(
        _record_get(raw, "output_tokens", _record_get(raw, "output_tokens_est", 0))
    )

    return ProductivityEvent(
        session_id=str(session_id_value) if session_id_value is not None else None,
        turn_index=_optional_int(turn_index_value),
        lines_changed=lines_changed,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        timestamp_ms=_optional_int(timestamp_value),
    )


def aggregate_productivity(events: Sequence[ProductivityEvent]) -> ProductivityStats:
    """Aggregate productivity events into one stats object."""

    return ProductivityStats(
        event_count=len(events),
        lines_changed=sum(event.effective_lines_changed for event in events),
        tokens_spent=sum(event.tokens_spent for event in events),
    )


def productivity_ratio(
    *,
    current_lines_per_token: float,
    baseline_lines_per_token: float,
) -> float | None:
    """Return current productivity divided by baseline productivity."""

    if baseline_lines_per_token <= 0:
        return None

    return current_lines_per_token / baseline_lines_per_token


def calibrate_low_productivity_score(
    ratio: float | None,
    *,
    threshold: float = DEFAULT_LOW_PRODUCTIVITY_RATIO_THRESHOLD,
) -> float:
    """Convert productivity ratio into a normalized badness score.

    Lower ratio means worse productivity.
    """

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")

    if ratio is None:
        return 0.0

    if ratio >= threshold:
        return 0.0

    if ratio >= threshold * 0.75:
        return 0.4

    if ratio >= threshold * 0.50:
        return 0.7

    return 0.95


def low_productivity_severity(score: float, *, has_enough_evidence: bool) -> Severity:
    """Map low-productivity score to severity."""

    if not has_enough_evidence:
        return Severity.INFO
    if score >= 0.90:
        return Severity.CRITICAL
    if score >= 0.60:
        return Severity.WARNING
    return Severity.INFO


def _baseline_from_explicit_ratio(
    *,
    baseline_lines_per_token: float,
    min_baseline_events: int,
    min_baseline_tokens: int,
) -> ProductivityStats:
    """Build synthetic baseline stats from an explicit ratio."""

    if baseline_lines_per_token <= 0:
        tokens = max(1, min_baseline_tokens)
        lines = 0
    else:
        tokens = max(min_baseline_tokens, ceil(1 / baseline_lines_per_token))
        lines = max(1, round(baseline_lines_per_token * tokens))

    return ProductivityStats(
        event_count=min_baseline_events,
        lines_changed=lines,
        tokens_spent=tokens,
    )


def evaluate_low_productivity(
    current_raw_events: Sequence[ProductivityEvent | Mapping[str, Any] | object],
    baseline_raw_events: Sequence[ProductivityEvent | Mapping[str, Any] | object] | None = None,
    *,
    baseline_lines_per_token: float | None = None,
    threshold: float = DEFAULT_LOW_PRODUCTIVITY_RATIO_THRESHOLD,
    min_current_events: int = DEFAULT_MIN_CURRENT_EVENTS,
    min_baseline_events: int = DEFAULT_MIN_BASELINE_EVENTS,
    min_current_tokens: int = DEFAULT_MIN_CURRENT_TOKENS,
    min_baseline_tokens: int = DEFAULT_MIN_BASELINE_TOKENS,
) -> LowProductivityResult:
    """Evaluate low productivity against a previous-session baseline."""

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")
    if min_current_events <= 0:
        raise ValueError("min_current_events must be greater than 0")
    if min_baseline_events <= 0:
        raise ValueError("min_baseline_events must be greater than 0")
    if min_current_tokens <= 0:
        raise ValueError("min_current_tokens must be greater than 0")
    if min_baseline_tokens <= 0:
        raise ValueError("min_baseline_tokens must be greater than 0")
    if baseline_lines_per_token is not None and baseline_lines_per_token < 0:
        raise ValueError("baseline_lines_per_token must be greater than or equal to 0")

    current_events = [normalise_productivity_event(item) for item in current_raw_events]
    current_stats = aggregate_productivity(current_events)

    if baseline_raw_events is not None:
        baseline_events = [normalise_productivity_event(item) for item in baseline_raw_events]
        baseline_stats: ProductivityStats | None = aggregate_productivity(baseline_events)
    elif baseline_lines_per_token is not None:
        baseline_stats = _baseline_from_explicit_ratio(
            baseline_lines_per_token=baseline_lines_per_token,
            min_baseline_events=min_baseline_events,
            min_baseline_tokens=min_baseline_tokens,
        )
    else:
        baseline_stats = None

    has_current_evidence = (
        current_stats.event_count >= min_current_events
        and current_stats.tokens_spent >= min_current_tokens
    )
    has_baseline_evidence = (
        baseline_stats is not None
        and baseline_stats.event_count >= min_baseline_events
        and baseline_stats.tokens_spent >= min_baseline_tokens
        and baseline_stats.lines_per_token > 0
    )
    has_enough_evidence = has_current_evidence and has_baseline_evidence

    ratio = (
        productivity_ratio(
            current_lines_per_token=current_stats.lines_per_token,
            baseline_lines_per_token=baseline_stats.lines_per_token,
        )
        if baseline_stats is not None
        else None
    )

    if not has_enough_evidence:
        score = 0.0
        baseline_event_count = 0 if baseline_stats is None else baseline_stats.event_count
        baseline_tokens = 0 if baseline_stats is None else baseline_stats.tokens_spent
        confidence = min(
            1.0,
            min(
                current_stats.event_count / min_current_events,
                current_stats.tokens_spent / min_current_tokens,
                baseline_event_count / min_baseline_events,
                baseline_tokens / min_baseline_tokens,
            ),
        )
        explanation = (
            f"Need current productivity evidence and a positive previous-session baseline. "
            f"Current events={current_stats.event_count}, current_tokens={current_stats.tokens_spent}; "
            f"baseline_events={baseline_event_count}, baseline_tokens={baseline_tokens}."
        )
    else:
        score = calibrate_low_productivity_score(ratio, threshold=threshold)
        confidence = 1.0
        ratio_text = "unknown" if ratio is None else f"{ratio:.2f}"
        assert baseline_stats is not None
        explanation = (
            f"Current productivity is {current_stats.lines_per_1k_tokens:.2f} lines/1k tokens "
            f"versus baseline {baseline_stats.lines_per_1k_tokens:.2f} lines/1k tokens "
            f"(ratio={ratio_text}, threshold<{threshold:.2f})."
        )

    return LowProductivityResult(
        signal_name=SignalName.LOW_PRODUCTIVITY,
        score=clamp_score(score),
        confidence=clamp_score(confidence),
        severity=low_productivity_severity(score, has_enough_evidence=has_enough_evidence),
        current_event_count=current_stats.event_count,
        baseline_event_count=0 if baseline_stats is None else baseline_stats.event_count,
        current_lines_changed=current_stats.lines_changed,
        current_tokens_spent=current_stats.tokens_spent,
        baseline_lines_changed=None if baseline_stats is None else baseline_stats.lines_changed,
        baseline_tokens_spent=None if baseline_stats is None else baseline_stats.tokens_spent,
        current_lines_per_1k_tokens=current_stats.lines_per_1k_tokens,
        baseline_lines_per_1k_tokens=None
        if baseline_stats is None
        else baseline_stats.lines_per_1k_tokens,
        productivity_ratio=ratio,
        threshold=threshold,
        min_current_events=min_current_events,
        min_baseline_events=min_baseline_events,
        min_current_tokens=min_current_tokens,
        min_baseline_tokens=min_baseline_tokens,
        explanation=explanation,
    )


class LowProductivitySignal:
    """Object-oriented wrapper for the low-productivity signal."""

    name = SignalName.LOW_PRODUCTIVITY

    def __init__(
        self,
        *,
        baseline_events: Sequence[ProductivityEvent | Mapping[str, Any] | object] | None = None,
        baseline_lines_per_token: float | None = None,
        threshold: float = DEFAULT_LOW_PRODUCTIVITY_RATIO_THRESHOLD,
        min_current_events: int = DEFAULT_MIN_CURRENT_EVENTS,
        min_baseline_events: int = DEFAULT_MIN_BASELINE_EVENTS,
        min_current_tokens: int = DEFAULT_MIN_CURRENT_TOKENS,
        min_baseline_tokens: int = DEFAULT_MIN_BASELINE_TOKENS,
    ) -> None:
        self.baseline_events = baseline_events
        self.baseline_lines_per_token = baseline_lines_per_token
        self.threshold = threshold
        self.min_current_events = min_current_events
        self.min_baseline_events = min_baseline_events
        self.min_current_tokens = min_current_tokens
        self.min_baseline_tokens = min_baseline_tokens

    def evaluate(
        self,
        current_events: Sequence[ProductivityEvent | Mapping[str, Any] | object],
    ) -> LowProductivityResult:
        """Evaluate this signal against current productivity events."""

        return evaluate_low_productivity(
            current_events,
            self.baseline_events,
            baseline_lines_per_token=self.baseline_lines_per_token,
            threshold=self.threshold,
            min_current_events=self.min_current_events,
            min_baseline_events=self.min_baseline_events,
            min_current_tokens=self.min_current_tokens,
            min_baseline_tokens=self.min_baseline_tokens,
        )
