"""Health score computation for Pilot sessions.

This module converts individual degradation signal results into one combined
session health score.

Design:
- each signal returns a 0..1 badness score
- weights come from pilot_core.constants.DEFAULT_SIGNAL_WEIGHTS
- multiple simultaneous fired signals apply an extra penalty
- final health score is clamped into 0..1
- derived state is based on the same health bands used by Pilot's state model
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pilot_core.constants import (
    DEFAULT_SIGNAL_WEIGHTS,
    Defaults,
    SessionState,
    SignalName,
    parse_signal_name,
)

DEFAULT_MULTI_SIGNAL_PENALTY_THRESHOLD = 3
DEFAULT_MULTI_SIGNAL_PENALTY_MULTIPLIER = 1.30
DEFAULT_FIRED_SCORE_THRESHOLD = 0.60


@dataclass(frozen=True)
class SignalHealthInput:
    """Normalised signal input used by health scoring."""

    signal_name: SignalName
    score: float
    confidence: float = 1.0
    fired: bool = False


@dataclass(frozen=True)
class SignalContribution:
    """Weighted contribution of one signal to session badness."""

    signal_name: SignalName
    score: float
    confidence: float
    weight: float
    weighted_badness: float
    fired: bool


@dataclass(frozen=True)
class HealthComputation:
    """Combined health score result."""

    health_score: float
    raw_badness_score: float
    adjusted_badness_score: float
    derived_state: SessionState
    observed_signal_count: int
    fired_count: int
    penalty_multiplier: float
    contributions: tuple[SignalContribution, ...]
    explanation: str

    @property
    def top_contributors(self) -> tuple[SignalContribution, ...]:
        """Return contributions sorted by weighted badness, highest first."""

        return tuple(
            sorted(
                self.contributions,
                key=lambda contribution: contribution.weighted_badness,
                reverse=True,
            )
        )

    @property
    def is_healthy(self) -> bool:
        """Return True when the derived state is healthy."""

        return self.derived_state is SessionState.HEALTHY

    @property
    def should_watch(self) -> bool:
        """Return True when the score is below healthy range."""

        return self.derived_state in {
            SessionState.WATCHING,
            SessionState.DEGRADING,
            SessionState.CRITICAL,
        }

    @property
    def should_escalate(self) -> bool:
        """Return True when the score is in degrading or critical territory."""

        return self.derived_state in {SessionState.DEGRADING, SessionState.CRITICAL}


def clamp_score(value: float) -> float:
    """Clamp a score into the 0..1 range."""

    return max(0.0, min(1.0, value))


def _safe_float(value: object, *, default: float = 0.0) -> float:
    """Convert a value to float without crashing on bad signal payloads."""

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
    """Read a key from a mapping-like or object-like record."""

    if isinstance(raw, Mapping):
        return raw.get(key, default)

    return getattr(raw, key, default)


def _normalise_signal_name(value: object) -> SignalName:
    """Convert a raw signal name into SignalName."""

    if isinstance(value, SignalName):
        return value

    if isinstance(value, str):
        return parse_signal_name(value)

    raise ValueError(f"Missing or invalid signal_name: {value!r}")


def normalise_health_input(
    raw: SignalHealthInput | Mapping[str, Any] | object,
    *,
    signal_name_hint: SignalName | str | None = None,
    fired_score_threshold: float = DEFAULT_FIRED_SCORE_THRESHOLD,
) -> SignalHealthInput:
    """Convert a signal result object/dict into SignalHealthInput."""

    if isinstance(raw, SignalHealthInput):
        return raw

    raw_name = _record_get(raw, "signal_name", signal_name_hint)
    signal_name = _normalise_signal_name(raw_name)

    score = clamp_score(_safe_float(_record_get(raw, "score", 0.0)))
    confidence = clamp_score(_safe_float(_record_get(raw, "confidence", 1.0), default=1.0))

    fired_value = _record_get(raw, "fired", None)
    fired = fired_value if isinstance(fired_value, bool) else score > fired_score_threshold

    return SignalHealthInput(
        signal_name=signal_name,
        score=score,
        confidence=confidence,
        fired=fired,
    )


def _iter_health_inputs(
    raw_results: Mapping[Any, object] | Sequence[object],
    *,
    fired_score_threshold: float,
) -> tuple[SignalHealthInput, ...]:
    """Return normalised health inputs from a mapping or sequence."""

    inputs: list[SignalHealthInput] = []

    if isinstance(raw_results, Mapping):
        for key, value in raw_results.items():
            hint = key if isinstance(key, SignalName | str) else None
            if isinstance(value, int | float):
                inputs.append(
                    normalise_health_input(
                        {"signal_name": hint, "score": value},
                        fired_score_threshold=fired_score_threshold,
                    )
                )
            else:
                inputs.append(
                    normalise_health_input(
                        value,
                        signal_name_hint=hint,
                        fired_score_threshold=fired_score_threshold,
                    )
                )
        return tuple(inputs)

    for value in raw_results:
        inputs.append(
            normalise_health_input(
                value,
                fired_score_threshold=fired_score_threshold,
            )
        )

    return tuple(inputs)


def derive_state_from_health(health_score: float) -> SessionState:
    """Map a health score to Pilot's coarse session state band."""

    score = clamp_score(health_score)

    if score >= Defaults.HEALTH_HEALTHY_MIN:
        return SessionState.HEALTHY

    if score >= Defaults.HEALTH_WATCHING_MIN:
        return SessionState.WATCHING

    if score >= Defaults.HEALTH_DEGRADING_MIN:
        return SessionState.DEGRADING

    return SessionState.CRITICAL


def compute_health_score(
    raw_results: Mapping[Any, object] | Sequence[object],
    *,
    weights: Mapping[SignalName, float] | None = None,
    multi_signal_penalty_threshold: int = DEFAULT_MULTI_SIGNAL_PENALTY_THRESHOLD,
    multi_signal_penalty_multiplier: float = DEFAULT_MULTI_SIGNAL_PENALTY_MULTIPLIER,
    fired_score_threshold: float = DEFAULT_FIRED_SCORE_THRESHOLD,
) -> HealthComputation:
    """Compute combined session health from signal results."""

    if multi_signal_penalty_threshold <= 0:
        raise ValueError("multi_signal_penalty_threshold must be greater than 0")

    if multi_signal_penalty_multiplier < 1.0:
        raise ValueError("multi_signal_penalty_multiplier must be greater than or equal to 1.0")

    resolved_weights = dict(weights or DEFAULT_SIGNAL_WEIGHTS)
    inputs = _iter_health_inputs(
        raw_results,
        fired_score_threshold=fired_score_threshold,
    )

    by_name: dict[SignalName, SignalHealthInput] = {}
    for item in inputs:
        by_name[item.signal_name] = item

    contributions: list[SignalContribution] = []
    raw_badness = 0.0

    for signal_name, item in by_name.items():
        weight = float(resolved_weights.get(signal_name, 0.0))
        weighted_badness = max(0.0, weight) * item.score
        raw_badness += weighted_badness

        contributions.append(
            SignalContribution(
                signal_name=signal_name,
                score=item.score,
                confidence=item.confidence,
                weight=weight,
                weighted_badness=weighted_badness,
                fired=item.fired,
            )
        )

    fired_count = sum(1 for contribution in contributions if contribution.fired)
    penalty_multiplier = (
        multi_signal_penalty_multiplier if fired_count >= multi_signal_penalty_threshold else 1.0
    )

    adjusted_badness = clamp_score(raw_badness * penalty_multiplier)
    health_score = clamp_score(1.0 - adjusted_badness)
    derived_state = derive_state_from_health(health_score)

    explanation = (
        f"health={health_score:.2f}, badness={adjusted_badness:.2f}, "
        f"fired={fired_count}, state={derived_state.value}"
    )

    return HealthComputation(
        health_score=health_score,
        raw_badness_score=clamp_score(raw_badness),
        adjusted_badness_score=adjusted_badness,
        derived_state=derived_state,
        observed_signal_count=len(contributions),
        fired_count=fired_count,
        penalty_multiplier=penalty_multiplier,
        contributions=tuple(contributions),
        explanation=explanation,
    )


def health_score_summary(result: HealthComputation) -> dict[str, object]:
    """Return a JSON-serialisable health score summary."""

    return {
        "health_score": result.health_score,
        "raw_badness_score": result.raw_badness_score,
        "adjusted_badness_score": result.adjusted_badness_score,
        "derived_state": result.derived_state.value,
        "observed_signal_count": result.observed_signal_count,
        "fired_count": result.fired_count,
        "penalty_multiplier": result.penalty_multiplier,
        "top_contributors": [
            {
                "signal_name": contribution.signal_name.value,
                "score": contribution.score,
                "confidence": contribution.confidence,
                "weight": contribution.weight,
                "weighted_badness": contribution.weighted_badness,
                "fired": contribution.fired,
            }
            for contribution in result.top_contributors
        ],
        "explanation": result.explanation,
    }
