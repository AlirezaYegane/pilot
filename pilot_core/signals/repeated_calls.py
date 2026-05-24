"""Repeated tool-call degradation signal.

This signal detects when the same tool is called repeatedly with effectively
the same input in a short recent window.

Why it matters:
- repeated identical calls often indicate loops
- loops burn context and rate limits
- this is one of the cheapest degradation signals to compute
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pilot_core.constants import Severity, SignalName


@dataclass(frozen=True)
class ToolCallFingerprint:
    """Stable fingerprint for a tool call."""

    tool_name: str
    input_hash: str


@dataclass(frozen=True)
class RepeatedCallsSignalResult:
    """Result payload for repeated-calls evaluation."""

    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    explanation: str
    repeat_count: int
    repeated_fingerprint: ToolCallFingerprint | None
    window_size: int


def _normalise_scalar(value: Any) -> Any:
    """Normalise scalar-like values for stable hashing."""

    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool | int | float) or value is None:
        return value
    return str(value)


def normalise_tool_input(value: Any) -> Any:
    """Return a JSON-stable representation of a tool input.

    Dict keys are sorted recursively, list order is preserved, and strings are
    stripped. This makes semantically identical payloads hash the same even if
    key order differs.
    """

    if isinstance(value, dict):
        return {
            str(key): normalise_tool_input(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }

    if isinstance(value, list | tuple):
        return [normalise_tool_input(item) for item in value]

    return _normalise_scalar(value)


def stable_tool_input_json(value: Any) -> str:
    """Serialise tool input into stable compact JSON."""

    normalised = normalise_tool_input(value)
    return json.dumps(
        normalised,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def hash_tool_input(value: Any) -> str:
    """Hash a normalised tool input using SHA-256."""

    payload = stable_tool_input_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_tool_call(tool_name: str, tool_input: Any) -> ToolCallFingerprint:
    """Create a stable fingerprint from tool name and input payload."""

    return ToolCallFingerprint(
        tool_name=tool_name.strip(),
        input_hash=hash_tool_input(tool_input),
    )


def repeated_call_score(repeat_count: int, *, threshold: int = 3) -> float:
    """Convert a repeat count into a normalised badness score.

    Score shape:
    - 0 or 1 occurrence: 0.0
    - 2 occurrences: early warning
    - threshold occurrences: actionable warning
    - threshold + 1 and above: high confidence degradation
    """

    if repeat_count <= 1:
        return 0.0
    if repeat_count < threshold:
        return 0.35
    if repeat_count == threshold:
        return 0.65
    return min(1.0, 0.65 + ((repeat_count - threshold) * 0.15))


def repeated_call_severity(score: float) -> Severity:
    """Map repeated-call score to severity."""

    if score >= 0.90:
        return Severity.CRITICAL
    if score >= 0.65:
        return Severity.WARNING
    if score > 0:
        return Severity.INFO
    return Severity.INFO


def evaluate_repeated_calls(
    recent_tool_calls: list[dict[str, Any]],
    *,
    window_size: int = 10,
    threshold: int = 3,
) -> RepeatedCallsSignalResult:
    """Evaluate repeated calls from recent tool call dictionaries.

    Expected item shape:
    {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest"}
    }

    Extra keys are ignored.
    """

    window = recent_tool_calls[-window_size:]

    fingerprints: list[ToolCallFingerprint] = []
    for item in window:
        tool_name = str(item.get("tool_name", "")).strip()
        tool_input = item.get("tool_input", {})

        if not tool_name:
            continue

        fingerprints.append(fingerprint_tool_call(tool_name, tool_input))

    if not fingerprints:
        return RepeatedCallsSignalResult(
            signal_name=SignalName.REPEATED_CALLS,
            score=0.0,
            confidence=0.0,
            severity=Severity.INFO,
            explanation="No recent tool calls available for repeated-call detection.",
            repeat_count=0,
            repeated_fingerprint=None,
            window_size=window_size,
        )

    counts = Counter(fingerprints)
    repeated_fingerprint, repeat_count = counts.most_common(1)[0]
    score = repeated_call_score(repeat_count, threshold=threshold)

    if score == 0:
        explanation = f"No repeated tool-call loop detected in the last {len(window)} tool calls."
        confidence = 0.75
    else:
        explanation = (
            f"{repeated_fingerprint.tool_name} was called {repeat_count} times "
            f"with the same normalised input in the last {len(window)} tool calls."
        )
        confidence = min(1.0, 0.50 + (repeat_count * 0.12))

    return RepeatedCallsSignalResult(
        signal_name=SignalName.REPEATED_CALLS,
        score=score,
        confidence=confidence,
        severity=repeated_call_severity(score),
        explanation=explanation,
        repeat_count=repeat_count,
        repeated_fingerprint=repeated_fingerprint if score > 0 else None,
        window_size=window_size,
    )
