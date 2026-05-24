# mypy: disable-error-code=misc
from __future__ import annotations

import pytest

from pilot_core.constants import ActivationMode, Severity, SignalName
from pilot_core.signals import (
    SignalDetector,
    SignalEvaluationContext,
    SignalEvidence,
    SignalResult,
    build_signal_result,
    clamp_unit_interval,
    confidence_from_observations,
    no_signal_result,
    score_to_severity,
)


def test_clamp_unit_interval_bounds_values() -> None:
    assert clamp_unit_interval(-1.0) == 0.0
    assert clamp_unit_interval(0.5) == 0.5
    assert clamp_unit_interval(2.0) == 1.0


def test_clamp_unit_interval_handles_nan() -> None:
    value = float("nan")
    assert clamp_unit_interval(value) == 0.0


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, Severity.INFO),
        (0.39, Severity.INFO),
        (0.40, Severity.WARNING),
        (0.69, Severity.WARNING),
        (0.70, Severity.ERROR),
        (0.89, Severity.ERROR),
        (0.90, Severity.CRITICAL),
        (1.0, Severity.CRITICAL),
    ],
)
def test_score_to_severity(score: float, expected: Severity) -> None:
    assert score_to_severity(score) is expected


def test_confidence_from_observations_scales_with_evidence() -> None:
    assert confidence_from_observations(0) == 0.0
    assert confidence_from_observations(1, minimum=2, strong=6) == 0.25
    assert confidence_from_observations(2, minimum=2, strong=6) == 0.5
    assert confidence_from_observations(6, minimum=2, strong=6) == 1.0


def test_confidence_from_observations_rejects_bad_thresholds() -> None:
    with pytest.raises(ValueError, match="minimum"):
        confidence_from_observations(1, minimum=0)

    with pytest.raises(ValueError, match="strong"):
        confidence_from_observations(1, minimum=5, strong=3)


def test_signal_evidence_as_dict_omits_empty_optional_fields() -> None:
    evidence = SignalEvidence(label="repeat_count")
    assert evidence.as_dict() == {"label": "repeat_count"}


def test_signal_evidence_as_dict_includes_present_fields() -> None:
    evidence = SignalEvidence(
        label="error_rate",
        value=0.6,
        unit="ratio",
        description="3 failures in 5 calls",
    )

    assert evidence.as_dict() == {
        "label": "error_rate",
        "value": 0.6,
        "unit": "ratio",
        "description": "3 failures in 5 calls",
    }


def test_build_signal_result_clamps_score_and_confidence() -> None:
    result = build_signal_result(
        name=SignalName.ERROR_CASCADE,
        score=2.0,
        confidence=-1.0,
        explanation="High failure rate.",
    )

    assert result.name is SignalName.ERROR_CASCADE
    assert result.score == 1.0
    assert result.confidence == 0.0
    assert result.severity is Severity.CRITICAL
    assert result.activation_mode is ActivationMode.SHADOW


def test_build_signal_result_accepts_evidence_and_metadata() -> None:
    result = build_signal_result(
        name=SignalName.REPEATED_CALLS,
        score=0.7,
        confidence=0.9,
        activation_mode=ActivationMode.WARN,
        explanation="Same tool input repeated.",
        evidence=(SignalEvidence(label="repeat_count", value=4),),
        metadata={"window_size": 10},
    )

    assert result.fired()
    assert result.is_actionable()
    assert result.as_dict() == {
        "name": "repeated_calls",
        "score": 0.7,
        "confidence": 0.9,
        "severity": "error",
        "activation_mode": "warn",
        "explanation": "Same tool input repeated.",
        "evidence": [{"label": "repeat_count", "value": 4}],
        "metadata": {"window_size": 10},
    }


def test_no_signal_result_is_standard_zero_result() -> None:
    result = no_signal_result(SignalName.TOKEN_BURN)

    assert result.name is SignalName.TOKEN_BURN
    assert result.score == 0.0
    assert result.confidence == 1.0
    assert result.severity is Severity.INFO
    assert result.activation_mode is ActivationMode.SHADOW
    assert not result.fired()


def test_shadow_result_is_not_actionable_even_when_fired() -> None:
    result = build_signal_result(
        name=SignalName.RATE_LIMIT,
        score=0.95,
        activation_mode=ActivationMode.SHADOW,
        explanation="Quota exhaustion is close.",
    )

    assert result.fired()
    assert not result.is_actionable()


def test_signal_evaluation_context_defaults_are_empty() -> None:
    context = SignalEvaluationContext(session_id="abc-123")

    assert context.session_id == "abc-123"
    assert context.turn_index is None
    assert context.now_ms is None
    assert context.config == {}
    assert context.metadata == {}


def test_signal_detector_protocol_accepts_detector_shape() -> None:
    class DummyDetector:
        name = SignalName.SELF_DOUBT

        def evaluate(self, context: SignalEvaluationContext) -> SignalResult:
            return no_signal_result(self.name, explanation=context.session_id)

    detector = DummyDetector()

    assert isinstance(detector, SignalDetector)
    assert detector.evaluate(SignalEvaluationContext(session_id="s1")).explanation == "s1"
