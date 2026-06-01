"""Token burn degradation signal.

This signal detects when recent token usage grows unusually fast compared with
the previous baseline window.

Default policy:
- compare the latest 3 turns against the previous 10 turns
- require enough evidence before firing
- fire when recent average tokens per turn is greater than baseline * 2.0
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

from pilot_core.constants import Severity, SignalName

DEFAULT_RECENT_TURN_WINDOW = 3
DEFAULT_BASELINE_TURN_WINDOW = 10
DEFAULT_TOKEN_BURN_RATIO_THRESHOLD = 2.0
DEFAULT_MIN_RECENT_TURNS = 2
DEFAULT_MIN_BASELINE_TURNS = 3


@dataclass(frozen=True)
class TurnTokenUsage:
    """Minimal token usage record for one user turn."""

    turn_index: int
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp_ms: int | None = None

    @property
    def total_tokens(self) -> int:
        """Return total estimated tokens for this turn."""

        return max(0, self.input_tokens) + max(0, self.output_tokens)


@dataclass(frozen=True)
class TokenBurnResult:
    """Result returned by the token burn signal."""

    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    recent_turn_count: int
    baseline_turn_count: int
    recent_average_tokens: float
    baseline_average_tokens: float
    ratio: float
    threshold: float
    min_recent_turns: int
    min_baseline_turns: int
    explanation: str

    @property
    def fired(self) -> bool:
        """Return True when token burn is strong enough to count as fired."""

        has_enough_recent = self.recent_turn_count >= self.min_recent_turns
        has_enough_baseline = self.baseline_turn_count >= self.min_baseline_turns
        return has_enough_recent and has_enough_baseline and self.ratio > self.threshold


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


def normalise_turn_token_usage(raw: TurnTokenUsage | Mapping[str, Any] | object) -> TurnTokenUsage:
    """Convert a dict/object/token record into TurnTokenUsage.

    Supported dict shapes:
    - {"turn_index": 1, "input_tokens": 100, "output_tokens": 50}
    - {"turn_index": 1, "input_tokens_est": 100, "output_tokens_est": 50}
    - {"turn_index": 1, "total_tokens": 150}
    """

    if isinstance(raw, TurnTokenUsage):
        return raw

    if isinstance(raw, Mapping):
        turn_index = _safe_int(raw.get("turn_index", 0))

        if "total_tokens" in raw:
            total_tokens = max(0, _safe_int(raw.get("total_tokens", 0)))
            return TurnTokenUsage(turn_index=turn_index, input_tokens=total_tokens, output_tokens=0)

        input_tokens = _safe_int(raw.get("input_tokens", raw.get("input_tokens_est", 0)))
        output_tokens = _safe_int(raw.get("output_tokens", raw.get("output_tokens_est", 0)))
        timestamp_value = raw.get("timestamp_ms")

        return TurnTokenUsage(
            turn_index=turn_index,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp_ms=_safe_int(timestamp_value) if timestamp_value is not None else None,
        )

    turn_index = _safe_int(getattr(raw, "turn_index", 0))

    total_tokens_attr = getattr(raw, "total_tokens", None)
    if total_tokens_attr is not None:
        total_tokens = max(0, _safe_int(total_tokens_attr))
        return TurnTokenUsage(turn_index=turn_index, input_tokens=total_tokens, output_tokens=0)

    input_tokens_attr = getattr(raw, "input_tokens", getattr(raw, "input_tokens_est", 0))
    output_tokens_attr = getattr(raw, "output_tokens", getattr(raw, "output_tokens_est", 0))
    timestamp_attr = getattr(raw, "timestamp_ms", None)

    return TurnTokenUsage(
        turn_index=turn_index,
        input_tokens=_safe_int(input_tokens_attr),
        output_tokens=_safe_int(output_tokens_attr),
        timestamp_ms=_safe_int(timestamp_attr) if timestamp_attr is not None else None,
    )


def recent_and_baseline_windows(
    usages: Sequence[TurnTokenUsage],
    *,
    recent_window: int = DEFAULT_RECENT_TURN_WINDOW,
    baseline_window: int = DEFAULT_BASELINE_TURN_WINDOW,
) -> tuple[tuple[TurnTokenUsage, ...], tuple[TurnTokenUsage, ...]]:
    """Split usage records into latest recent window and previous baseline window."""

    if recent_window <= 0:
        raise ValueError("recent_window must be greater than 0")
    if baseline_window <= 0:
        raise ValueError("baseline_window must be greater than 0")

    ordered = tuple(usages)
    recent = ordered[-recent_window:]

    baseline_end = max(0, len(ordered) - recent_window)
    baseline_start = max(0, baseline_end - baseline_window)
    baseline = ordered[baseline_start:baseline_end]

    return recent, baseline


def average_tokens_per_turn(usages: Sequence[TurnTokenUsage]) -> float:
    """Return average total token usage for a sequence of turns."""

    if not usages:
        return 0.0

    return sum(item.total_tokens for item in usages) / len(usages)


def token_burn_ratio(recent_average: float, baseline_average: float) -> float:
    """Return recent/baseline ratio with safe zero-baseline handling."""

    if baseline_average <= 0:
        return 0.0 if recent_average <= 0 else float("inf")

    return recent_average / baseline_average


def calibrate_token_burn_score(
    ratio: float,
    *,
    threshold: float = DEFAULT_TOKEN_BURN_RATIO_THRESHOLD,
) -> float:
    """Convert a token burn ratio into a normalized badness score."""

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")

    if not isfinite(ratio):
        return 1.0

    if ratio < threshold * 0.75:
        return 0.0
    if ratio < threshold:
        return 0.4
    if ratio < threshold * 1.5:
        return 0.7
    return 0.95


def token_burn_severity(score: float, *, has_enough_evidence: bool) -> Severity:
    """Map token burn score to severity."""

    if not has_enough_evidence:
        return Severity.INFO
    if score >= 0.90:
        return Severity.CRITICAL
    if score >= 0.60:
        return Severity.WARNING
    return Severity.INFO


def evaluate_token_burn(
    raw_usages: Sequence[TurnTokenUsage | Mapping[str, Any] | object],
    *,
    recent_window: int = DEFAULT_RECENT_TURN_WINDOW,
    baseline_window: int = DEFAULT_BASELINE_TURN_WINDOW,
    threshold: float = DEFAULT_TOKEN_BURN_RATIO_THRESHOLD,
    min_recent_turns: int = DEFAULT_MIN_RECENT_TURNS,
    min_baseline_turns: int = DEFAULT_MIN_BASELINE_TURNS,
) -> TokenBurnResult:
    """Evaluate the token burn signal for recent turn-level token usage."""

    if min_recent_turns <= 0:
        raise ValueError("min_recent_turns must be greater than 0")
    if min_baseline_turns <= 0:
        raise ValueError("min_baseline_turns must be greater than 0")

    normalised = [normalise_turn_token_usage(item) for item in raw_usages]
    recent, baseline = recent_and_baseline_windows(
        tuple(normalised),
        recent_window=recent_window,
        baseline_window=baseline_window,
    )

    recent_average = average_tokens_per_turn(recent)
    baseline_average = average_tokens_per_turn(baseline)
    ratio = token_burn_ratio(recent_average, baseline_average)

    has_enough_recent = len(recent) >= min_recent_turns
    has_enough_baseline = len(baseline) >= min_baseline_turns
    has_enough_evidence = has_enough_recent and has_enough_baseline

    if not has_enough_evidence:
        score = 0.0
        confidence = min(
            1.0,
            min(
                len(recent) / min_recent_turns,
                len(baseline) / min_baseline_turns,
            ),
        )
        explanation = (
            f"Only {len(recent)} recent turn(s) and {len(baseline)} baseline turn(s) observed; "
            f"need at least {min_recent_turns} recent and {min_baseline_turns} baseline turns."
        )
    else:
        score = calibrate_token_burn_score(ratio, threshold=threshold)
        confidence = min(1.0, min(len(recent) / recent_window, len(baseline) / baseline_window))
        explanation = (
            f"Recent average token usage is {recent_average:.1f} tokens/turn versus "
            f"baseline {baseline_average:.1f} tokens/turn "
            f"(ratio={ratio:.2f}, threshold>{threshold:.2f})."
        )

    return TokenBurnResult(
        signal_name=SignalName.TOKEN_BURN,
        score=clamp_score(score),
        confidence=clamp_score(confidence),
        severity=token_burn_severity(score, has_enough_evidence=has_enough_evidence),
        recent_turn_count=len(recent),
        baseline_turn_count=len(baseline),
        recent_average_tokens=recent_average,
        baseline_average_tokens=baseline_average,
        ratio=ratio,
        threshold=threshold,
        min_recent_turns=min_recent_turns,
        min_baseline_turns=min_baseline_turns,
        explanation=explanation,
    )


class TokenBurnSignal:
    """Object-oriented wrapper for the token burn signal."""

    name = SignalName.TOKEN_BURN

    def __init__(
        self,
        *,
        recent_window: int = DEFAULT_RECENT_TURN_WINDOW,
        baseline_window: int = DEFAULT_BASELINE_TURN_WINDOW,
        threshold: float = DEFAULT_TOKEN_BURN_RATIO_THRESHOLD,
        min_recent_turns: int = DEFAULT_MIN_RECENT_TURNS,
        min_baseline_turns: int = DEFAULT_MIN_BASELINE_TURNS,
    ) -> None:
        self.recent_window = recent_window
        self.baseline_window = baseline_window
        self.threshold = threshold
        self.min_recent_turns = min_recent_turns
        self.min_baseline_turns = min_baseline_turns

    def evaluate(
        self,
        raw_usages: Sequence[TurnTokenUsage | Mapping[str, Any] | object],
    ) -> TokenBurnResult:
        """Evaluate this signal against recent turn-level token usage."""

        return evaluate_token_burn(
            raw_usages,
            recent_window=self.recent_window,
            baseline_window=self.baseline_window,
            threshold=self.threshold,
            min_recent_turns=self.min_recent_turns,
            min_baseline_turns=self.min_baseline_turns,
        )
