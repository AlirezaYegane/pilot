"""Signal implementations for Pilot."""

from pilot_core.signals.error_cascade import (
    DEFAULT_ERROR_CASCADE_THRESHOLD,
    DEFAULT_ERROR_CASCADE_WINDOW,
    DEFAULT_MIN_OBSERVATIONS,
    ErrorCascadeResult,
    ErrorCascadeSignal,
    ToolOutcome,
    calibrate_error_cascade_score,
    evaluate_error_cascade,
    failure_rate,
    normalise_tool_outcome,
    recent_outcomes,
)

__all__ = [
    "DEFAULT_ERROR_CASCADE_THRESHOLD",
    "DEFAULT_ERROR_CASCADE_WINDOW",
    "DEFAULT_MIN_OBSERVATIONS",
    "ErrorCascadeResult",
    "ErrorCascadeSignal",
    "ToolOutcome",
    "calibrate_error_cascade_score",
    "evaluate_error_cascade",
    "failure_rate",
    "normalise_tool_outcome",
    "recent_outcomes",
]
