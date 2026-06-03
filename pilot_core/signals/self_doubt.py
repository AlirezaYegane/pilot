"""Self-doubt degradation signal.

This signal detects repeated assistant uncertainty / repair-loop markers.

Default policy:
- inspect recent assistant messages
- count conservative self-doubt phrases
- fire when marker_count >= 3

Examples:
- "let me try again"
- "I see the issue now"
- "I was wrong"
- "that did not work"
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from re import Pattern
from typing import Any

from pilot_core.constants import Severity, SignalName

DEFAULT_SELF_DOUBT_WINDOW = 8
DEFAULT_SELF_DOUBT_THRESHOLD = 3
DEFAULT_MIN_ASSISTANT_MESSAGES = 1

DEFAULT_SELF_DOUBT_PATTERNS: tuple[str, ...] = (
    r"\blet me try again\b",
    r"\bi see the issue now\b",
    r"\bi found the issue\b",
    r"\bi was wrong\b",
    r"\bi made a mistake\b",
    r"\bmy mistake\b",
    r"\bthat did not work\b",
    r"\bthat didn't work\b",
    r"\bthis did not work\b",
    r"\bthis didn't work\b",
    r"\btry another approach\b",
    r"\bi need to rethink\b",
    r"\bi missed\b",
    r"\bi misread\b",
    r"\bsorry\b.{0,80}\b(?:mistake|wrong|issue|error)\b",
)


@dataclass(frozen=True)
class AssistantMessage:
    """Minimal assistant-message record used by self-doubt detection."""

    text: str
    turn_index: int | None = None
    timestamp_ms: int | None = None


@dataclass(frozen=True)
class SelfDoubtMarker:
    """One matched self-doubt marker."""

    phrase: str
    pattern: str
    message_index: int


@dataclass(frozen=True)
class SelfDoubtResult:
    """Result returned by the self-doubt signal."""

    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    observed_message_count: int
    marker_count: int
    unique_marker_count: int
    matched_phrases: tuple[str, ...]
    window_size: int
    threshold: int
    min_assistant_messages: int
    explanation: str

    @property
    def fired(self) -> bool:
        """Return True when enough self-doubt markers were observed."""

        has_enough_messages = self.observed_message_count >= self.min_assistant_messages
        return has_enough_messages and self.marker_count >= self.threshold


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


def _stringify_text(value: object) -> str:
    """Convert common message content shapes into plain text."""

    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, list | tuple):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                nested_text = item.get("text", item.get("content", ""))
                parts.append(_stringify_text(nested_text))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)

    if isinstance(value, Mapping):
        for key in ("text", "content", "message", "response", "body"):
            if key in value:
                return _stringify_text(value[key])
        return str(dict(value))

    return str(value)


def extract_assistant_text(raw: object) -> str:
    """Extract assistant text from common hook, replay, and test payloads."""

    for key in (
        "text",
        "content",
        "message",
        "response",
        "assistant_response",
        "assistant_message",
        "output",
        "body",
    ):
        value = _record_get(raw, key, None)
        text = _stringify_text(value).strip()
        if text:
            return text

    tool_response = _record_get(raw, "tool_response", None)
    text = _stringify_text(tool_response).strip()
    if text:
        return text

    return ""


def normalise_assistant_message(
    raw: AssistantMessage | Mapping[str, Any] | object,
) -> AssistantMessage:
    """Convert a dict/object/replay record into AssistantMessage."""

    if isinstance(raw, AssistantMessage):
        return raw

    text = extract_assistant_text(raw)
    turn_index_value = _record_get(raw, "turn_index", None)
    timestamp_value = _record_get(raw, "timestamp_ms", None)

    return AssistantMessage(
        text=text,
        turn_index=_safe_int(turn_index_value) if turn_index_value is not None else None,
        timestamp_ms=_safe_int(timestamp_value) if timestamp_value is not None else None,
    )


def compile_self_doubt_patterns(
    patterns: Sequence[str] = DEFAULT_SELF_DOUBT_PATTERNS,
) -> tuple[Pattern[str], ...]:
    """Compile self-doubt regex patterns."""

    return tuple(re.compile(pattern, flags=re.IGNORECASE | re.DOTALL) for pattern in patterns)


def recent_assistant_messages(
    messages: Sequence[AssistantMessage],
    *,
    window_size: int = DEFAULT_SELF_DOUBT_WINDOW,
) -> tuple[AssistantMessage, ...]:
    """Return the latest assistant messages inside the rolling window."""

    if window_size <= 0:
        raise ValueError("window_size must be greater than 0")

    return tuple(messages[-window_size:])


def find_self_doubt_markers(
    messages: Sequence[AssistantMessage],
    *,
    patterns: Sequence[str] = DEFAULT_SELF_DOUBT_PATTERNS,
) -> tuple[SelfDoubtMarker, ...]:
    """Find self-doubt markers in assistant messages."""

    compiled_patterns = compile_self_doubt_patterns(patterns)
    markers: list[SelfDoubtMarker] = []

    for message_index, message in enumerate(messages):
        text = message.text.strip()
        if not text:
            continue

        for pattern_text, pattern in zip(patterns, compiled_patterns, strict=True):
            for match in pattern.finditer(text):
                phrase = " ".join(match.group(0).split())
                markers.append(
                    SelfDoubtMarker(
                        phrase=phrase,
                        pattern=pattern_text,
                        message_index=message_index,
                    )
                )

    return tuple(markers)


def calibrate_self_doubt_score(
    marker_count: int,
    *,
    threshold: int = DEFAULT_SELF_DOUBT_THRESHOLD,
) -> float:
    """Convert marker count into a normalized badness score."""

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")

    if marker_count <= 0:
        return 0.0
    if marker_count < threshold:
        return 0.4
    if marker_count == threshold:
        return 0.7
    return 0.95


def self_doubt_severity(score: float, *, has_enough_evidence: bool) -> Severity:
    """Map score and evidence size to severity."""

    if not has_enough_evidence:
        return Severity.INFO
    if score >= 0.90:
        return Severity.CRITICAL
    if score >= 0.60:
        return Severity.WARNING
    return Severity.INFO


def evaluate_self_doubt(
    raw_messages: Sequence[AssistantMessage | Mapping[str, Any] | object],
    *,
    window_size: int = DEFAULT_SELF_DOUBT_WINDOW,
    threshold: int = DEFAULT_SELF_DOUBT_THRESHOLD,
    min_assistant_messages: int = DEFAULT_MIN_ASSISTANT_MESSAGES,
    patterns: Sequence[str] = DEFAULT_SELF_DOUBT_PATTERNS,
) -> SelfDoubtResult:
    """Evaluate self-doubt markers in recent assistant messages."""

    if min_assistant_messages <= 0:
        raise ValueError("min_assistant_messages must be greater than 0")

    messages = [normalise_assistant_message(item) for item in raw_messages]
    recent_messages = recent_assistant_messages(messages, window_size=window_size)
    markers = find_self_doubt_markers(recent_messages, patterns=patterns)

    marker_count = len(markers)
    unique_phrases = tuple(sorted({marker.phrase.lower() for marker in markers}))
    has_enough_evidence = len(recent_messages) >= min_assistant_messages

    if not has_enough_evidence:
        score = 0.0
        confidence = len(recent_messages) / min_assistant_messages
        explanation = (
            f"Only {len(recent_messages)} assistant message(s) observed; "
            f"need at least {min_assistant_messages} before judging self-doubt."
        )
    else:
        score = calibrate_self_doubt_score(marker_count, threshold=threshold)
        confidence = min(1.0, len(recent_messages) / max(1, min(window_size, threshold)))
        phrases_text = ", ".join(unique_phrases) if unique_phrases else "none"
        explanation = (
            f"Detected {marker_count} self-doubt marker(s) in the last "
            f"{window_size} assistant message(s) "
            f"(threshold>={threshold}, markers={phrases_text})."
        )

    return SelfDoubtResult(
        signal_name=SignalName.SELF_DOUBT,
        score=clamp_score(score),
        confidence=clamp_score(confidence),
        severity=self_doubt_severity(score, has_enough_evidence=has_enough_evidence),
        observed_message_count=len(recent_messages),
        marker_count=marker_count,
        unique_marker_count=len(unique_phrases),
        matched_phrases=unique_phrases,
        window_size=window_size,
        threshold=threshold,
        min_assistant_messages=min_assistant_messages,
        explanation=explanation,
    )


class SelfDoubtSignal:
    """Object-oriented wrapper for the self-doubt signal."""

    name = SignalName.SELF_DOUBT

    def __init__(
        self,
        *,
        window_size: int = DEFAULT_SELF_DOUBT_WINDOW,
        threshold: int = DEFAULT_SELF_DOUBT_THRESHOLD,
        min_assistant_messages: int = DEFAULT_MIN_ASSISTANT_MESSAGES,
        patterns: Sequence[str] = DEFAULT_SELF_DOUBT_PATTERNS,
    ) -> None:
        self.window_size = window_size
        self.threshold = threshold
        self.min_assistant_messages = min_assistant_messages
        self.patterns = tuple(patterns)

    def evaluate(
        self,
        raw_messages: Sequence[AssistantMessage | Mapping[str, Any] | object],
    ) -> SelfDoubtResult:
        """Evaluate this signal against recent assistant messages."""

        return evaluate_self_doubt(
            raw_messages,
            window_size=self.window_size,
            threshold=self.threshold,
            min_assistant_messages=self.min_assistant_messages,
            patterns=self.patterns,
        )
