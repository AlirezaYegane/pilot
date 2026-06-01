"""Error cascade degradation signal.

This signal detects when a session starts failing repeatedly.

The default policy follows Pilot's core signal plan:
- inspect the latest 5 tool outcomes
- require at least 3 observed outcomes before scoring
- treat a failure rate above 40% as a strong cascade signal

The implementation is intentionally small and pure so it can be used by:
- unit tests
- future replay fixtures
- the signal registry
- the real hook-driven decision engine
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pilot_core.constants import Severity, SignalName

DEFAULT_ERROR_CASCADE_WINDOW = 5
DEFAULT_ERROR_CASCADE_THRESHOLD = 0.40
DEFAULT_MIN_OBSERVATIONS = 3


@dataclass(frozen=True)
class ToolOutcome:
    """Minimal success/failure view of a tool call."""

    success: bool
    tool_name: str | None = None
    timestamp_ms: int | None = None


@dataclass(frozen=True)
class ErrorCascadeResult:
    """Result returned by the error cascade signal."""

    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    window_size: int
    observed_count: int
    failure_count: int
    failure_rate: float
    threshold: float
    explanation: str

    @property
    def fired(self) -> bool:
        """Return True when the signal is strong enough to count as fired."""

        return (
            self.failure_rate > self.threshold and self.observed_count >= DEFAULT_MIN_OBSERVATIONS
        )


def clamp_score(value: float) -> float:
    """Clamp a score into the 0..1 range."""

    return max(0.0, min(1.0, value))


def normalise_tool_outcome(raw: ToolOutcome | dict[str, Any] | object) -> ToolOutcome:
    """Convert a dict/object/tool record into a ToolOutcome.

    Supported shapes:
    - ToolOutcome(success=True)
    - {"success": true}
    - {"success": false, "tool_name": "Bash"}
    - {"error": {...}} means failure
    - object with .success, .tool_name, .timestamp_ms attributes
    """

    if isinstance(raw, ToolOutcome):
        return raw

    if isinstance(raw, dict):
        success = bool(raw["success"]) if "success" in raw else raw.get("error") in (None, {}, "")

        tool_name = raw.get("tool_name")
        timestamp_value = raw.get("timestamp_ms")

        return ToolOutcome(
            success=success,
            tool_name=str(tool_name) if tool_name is not None else None,
            timestamp_ms=int(timestamp_value) if timestamp_value is not None else None,
        )

    success_attr = getattr(raw, "success", None)
    if success_attr is not None:
        success = bool(success_attr)
    else:
        error_attr = getattr(raw, "error", None)
        success = error_attr in (None, {}, "")

    tool_name_attr = getattr(raw, "tool_name", None)
    timestamp_attr = getattr(raw, "timestamp_ms", None)

    return ToolOutcome(
        success=success,
        tool_name=str(tool_name_attr) if tool_name_attr is not None else None,
        timestamp_ms=int(timestamp_attr) if timestamp_attr is not None else None,
    )


def recent_outcomes(
    outcomes: list[ToolOutcome] | tuple[ToolOutcome, ...],
    *,
    window_size: int = DEFAULT_ERROR_CASCADE_WINDOW,
) -> tuple[ToolOutcome, ...]:
    """Return the latest outcomes inside the rolling window."""

    if window_size <= 0:
        raise ValueError("window_size must be greater than 0")

    return tuple(outcomes[-window_size:])


def failure_rate(outcomes: tuple[ToolOutcome, ...]) -> float:
    """Return the failure rate for a sequence of outcomes."""

    if not outcomes:
        return 0.0

    failures = sum(1 for outcome in outcomes if not outcome.success)
    return failures / len(outcomes)


def calibrate_error_cascade_score(
    rate: float,
    *,
    threshold: float = DEFAULT_ERROR_CASCADE_THRESHOLD,
) -> float:
    """Convert a failure rate into a normalized badness score.

    A rate equal to the threshold maps to 1.0. Lower rates still produce
    partial scores, which lets the future combined health score react smoothly.
    """

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")

    return clamp_score(rate / threshold)


def error_cascade_severity(score: float, *, observed_count: int) -> Severity:
    """Map score and evidence size to a severity level."""

    if observed_count < DEFAULT_MIN_OBSERVATIONS:
        return Severity.INFO
    if score >= 0.90:
        return Severity.CRITICAL
    if score >= 0.60:
        return Severity.WARNING
    return Severity.INFO


def evaluate_error_cascade(
    raw_outcomes: list[ToolOutcome | dict[str, Any] | object]
    | tuple[ToolOutcome | dict[str, Any] | object, ...],
    *,
    window_size: int = DEFAULT_ERROR_CASCADE_WINDOW,
    threshold: float = DEFAULT_ERROR_CASCADE_THRESHOLD,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> ErrorCascadeResult:
    """Evaluate the error cascade signal for recent tool outcomes."""

    if min_observations <= 0:
        raise ValueError("min_observations must be greater than 0")

    normalised = [normalise_tool_outcome(item) for item in raw_outcomes]
    window = recent_outcomes(tuple(normalised), window_size=window_size)

    observed_count = len(window)
    failure_count = sum(1 for outcome in window if not outcome.success)
    rate = failure_rate(window)

    if observed_count < min_observations:
        score = 0.0
        confidence = observed_count / min_observations
        explanation = (
            f"Only {observed_count} tool outcome(s) observed; "
            f"need at least {min_observations} before judging error cascade."
        )
    else:
        score = calibrate_error_cascade_score(rate, threshold=threshold)
        confidence = min(1.0, observed_count / window_size)
        explanation = (
            f"{failure_count}/{observed_count} recent tool call(s) failed "
            f"inside the last {window_size} outcomes "
            f"(failure_rate={rate:.2f}, threshold>{threshold:.2f})."
        )

    return ErrorCascadeResult(
        signal_name=SignalName.ERROR_CASCADE,
        score=score,
        confidence=clamp_score(confidence),
        severity=error_cascade_severity(score, observed_count=observed_count),
        window_size=window_size,
        observed_count=observed_count,
        failure_count=failure_count,
        failure_rate=rate,
        threshold=threshold,
        explanation=explanation,
    )


class ErrorCascadeSignal:
    """Object-oriented wrapper for the error cascade signal."""

    name = SignalName.ERROR_CASCADE

    def __init__(
        self,
        *,
        window_size: int = DEFAULT_ERROR_CASCADE_WINDOW,
        threshold: float = DEFAULT_ERROR_CASCADE_THRESHOLD,
        min_observations: int = DEFAULT_MIN_OBSERVATIONS,
    ) -> None:
        self.window_size = window_size
        self.threshold = threshold
        self.min_observations = min_observations

    def evaluate(
        self,
        raw_outcomes: list[ToolOutcome | dict[str, Any] | object]
        | tuple[ToolOutcome | dict[str, Any] | object, ...],
    ) -> ErrorCascadeResult:
        """Evaluate this signal against recent tool outcomes."""

        return evaluate_error_cascade(
            raw_outcomes,
            window_size=self.window_size,
            threshold=self.threshold,
            min_observations=self.min_observations,
        )
