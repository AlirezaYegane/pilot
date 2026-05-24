"""Signal interfaces and implementations for Pilot."""

from pilot_core.signals.base import (
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
from pilot_core.signals.repeated_calls import (
    RepeatedCallsSignalResult,
    ToolCallFingerprint,
    evaluate_repeated_calls,
    fingerprint_tool_call,
    hash_tool_input,
    normalise_tool_input,
    repeated_call_score,
    repeated_call_severity,
    stable_tool_input_json,
)

__all__ = [
    "RepeatedCallsSignalResult",
    "SignalDetector",
    "SignalEvaluationContext",
    "SignalEvidence",
    "SignalResult",
    "ToolCallFingerprint",
    "build_signal_result",
    "clamp_unit_interval",
    "confidence_from_observations",
    "evaluate_repeated_calls",
    "fingerprint_tool_call",
    "hash_tool_input",
    "no_signal_result",
    "normalise_tool_input",
    "repeated_call_score",
    "repeated_call_severity",
    "score_to_severity",
    "stable_tool_input_json",
]
