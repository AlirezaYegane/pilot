"""Base contracts for Pilot degradation signals.

Signal implementations should stay small, deterministic, and cheap to run.
This module defines the shared input/output contract that every signal uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pilot_core.constants import ActivationMode, Severity, SignalName

JsonPrimitive = str | int | float | bool | None
MetadataValue = JsonPrimitive | list[JsonPrimitive] | dict[str, JsonPrimitive]
Metadata = dict[str, MetadataValue]


def _empty_metadata() -> Metadata:
    """Return a new empty metadata dictionary."""

    return {}


@dataclass(frozen=True)
class SignalEvaluationContext:
    """Context object passed to every signal detector."""

    session_id: str
    turn_index: int | None = None
    now_ms: int | None = None
    config: Metadata = field(default_factory=_empty_metadata)
    metadata: Metadata = field(default_factory=_empty_metadata)


@dataclass(frozen=True)
class SignalEvidence:
    """Small evidence item explaining why a signal produced a score."""

    label: str
    value: JsonPrimitive = None
    unit: str | None = None
    description: str = ""

    def as_dict(self) -> dict[str, JsonPrimitive]:
        """Return a compact serialisable representation."""

        data: dict[str, JsonPrimitive] = {"label": self.label}
        if self.value is not None:
            data["value"] = self.value
        if self.unit is not None:
            data["unit"] = self.unit
        if self.description:
            data["description"] = self.description
        return data


@dataclass(frozen=True)
class SignalResult:
    """Normalised output from a degradation signal."""

    name: SignalName
    score: float
    confidence: float
    severity: Severity
    activation_mode: ActivationMode
    explanation: str
    evidence: tuple[SignalEvidence, ...] = ()
    metadata: Metadata = field(default_factory=_empty_metadata)

    def fired(self, *, threshold: float = 0.60) -> bool:
        """Return True when the score crosses a detection threshold."""

        return self.score >= threshold

    def is_actionable(self, *, threshold: float = 0.60) -> bool:
        """Return True when the result should be considered by action policy."""

        return self.activation_mode is not ActivationMode.SHADOW and self.fired(threshold=threshold)

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation for storage and CLI output."""

        return {
            "name": self.name.value,
            "score": self.score,
            "confidence": self.confidence,
            "severity": self.severity.value,
            "activation_mode": self.activation_mode.value,
            "explanation": self.explanation,
            "evidence": [item.as_dict() for item in self.evidence],
            "metadata": self.metadata,
        }


@runtime_checkable
class SignalDetector(Protocol):
    """Protocol implemented by all signal detectors."""

    name: SignalName

    def evaluate(self, context: SignalEvaluationContext) -> SignalResult:
        """Evaluate one signal for a session."""


def clamp_unit_interval(value: float) -> float:
    """Clamp a score-like value into the [0, 1] interval."""

    if value != value:
        return 0.0
    return max(0.0, min(1.0, value))


def score_to_severity(score: float) -> Severity:
    """Convert a normalised badness score into a severity label."""

    bounded_score = clamp_unit_interval(score)
    if bounded_score >= 0.90:
        return Severity.CRITICAL
    if bounded_score >= 0.70:
        return Severity.ERROR
    if bounded_score >= 0.40:
        return Severity.WARNING
    return Severity.INFO


def confidence_from_observations(
    observation_count: int,
    *,
    minimum: int = 3,
    strong: int = 10,
) -> float:
    """Estimate confidence from the amount of evidence available."""

    if minimum <= 0:
        raise ValueError("minimum must be greater than zero")
    if strong < minimum:
        raise ValueError("strong must be greater than or equal to minimum")
    if observation_count <= 0:
        return 0.0
    if observation_count < minimum:
        return clamp_unit_interval((observation_count / minimum) * 0.5)
    if observation_count >= strong:
        return 1.0

    span = max(1, strong - minimum)
    return clamp_unit_interval(0.5 + ((observation_count - minimum) / span) * 0.5)


def build_signal_result(
    *,
    name: SignalName,
    score: float,
    explanation: str,
    confidence: float = 1.0,
    activation_mode: ActivationMode = ActivationMode.SHADOW,
    evidence: tuple[SignalEvidence, ...] = (),
    metadata: Metadata | None = None,
    severity: Severity | None = None,
) -> SignalResult:
    """Build a normalised signal result with score/confidence clamping."""

    bounded_score = clamp_unit_interval(score)
    bounded_confidence = clamp_unit_interval(confidence)

    return SignalResult(
        name=name,
        score=bounded_score,
        confidence=bounded_confidence,
        severity=severity or score_to_severity(bounded_score),
        activation_mode=activation_mode,
        explanation=explanation,
        evidence=evidence,
        metadata=metadata or {},
    )


def no_signal_result(
    name: SignalName,
    *,
    explanation: str = "No signal detected.",
    activation_mode: ActivationMode = ActivationMode.SHADOW,
) -> SignalResult:
    """Return a standard zero-score signal result."""

    return build_signal_result(
        name=name,
        score=0.0,
        confidence=1.0,
        severity=Severity.INFO,
        activation_mode=activation_mode,
        explanation=explanation,
    )
