"""Context saturation degradation signal.

This signal estimates how close a session is to the model context limit.

Pilot cannot directly read the real Claude Code context window. Instead, it
uses cumulative estimated token usage plus a conservative system-prompt offset.

Default policy:
- cumulative context tokens = sum(input + output tokens) + system prompt offset
- default model limit = 200k tokens
- saturation fires when estimated context ratio is greater than 0.80
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pilot_core.constants import Defaults, Severity, SignalName

DEFAULT_CONTEXT_SATURATION_THRESHOLD = 0.80
DEFAULT_MIN_TOKEN_EVENTS = 1

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude-3-5-sonnet": 200_000,
    "claude-3-7-sonnet": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-opus-4": 200_000,
    "claude-sonnet-4-1m": 1_000_000,
    "claude-opus-4-1m": 1_000_000,
    "claude-1m": 1_000_000,
}


@dataclass(frozen=True)
class TokenEvent:
    """Minimal token record for one tool call or turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    timestamp_ms: int | None = None
    model_name: str | None = None

    @property
    def total_tokens(self) -> int:
        """Return non-negative total token usage for this event."""

        return max(0, self.input_tokens) + max(0, self.output_tokens)


@dataclass(frozen=True)
class ContextSaturationResult:
    """Result returned by the context saturation signal."""

    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    observed_event_count: int
    context_tokens: int
    model_context_limit: int
    saturation_ratio: float
    threshold: float
    system_prompt_token_offset: int
    min_token_events: int
    model_name: str | None
    explanation: str

    @property
    def fired(self) -> bool:
        """Return True when estimated context saturation is above threshold."""

        has_enough_evidence = self.observed_event_count >= self.min_token_events
        return has_enough_evidence and self.saturation_ratio > self.threshold


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


def normalise_token_event(raw: TokenEvent | Mapping[str, Any] | object) -> TokenEvent:
    """Convert a dict/object/token record into TokenEvent.

    Supported dict shapes:
    - {"input_tokens": 100, "output_tokens": 50}
    - {"input_tokens_est": 100, "output_tokens_est": 50}
    - {"total_tokens": 150}
    - {"model_name": "claude-sonnet-4"}
    """

    if isinstance(raw, TokenEvent):
        return raw

    if isinstance(raw, Mapping):
        model_name = raw.get("model_name", raw.get("model"))
        timestamp_value = raw.get("timestamp_ms")

        if "total_tokens" in raw:
            total_tokens = max(0, _safe_int(raw.get("total_tokens", 0)))
            return TokenEvent(
                input_tokens=total_tokens,
                output_tokens=0,
                timestamp_ms=_safe_int(timestamp_value) if timestamp_value is not None else None,
                model_name=str(model_name) if model_name is not None else None,
            )

        input_tokens = _safe_int(raw.get("input_tokens", raw.get("input_tokens_est", 0)))
        output_tokens = _safe_int(raw.get("output_tokens", raw.get("output_tokens_est", 0)))

        return TokenEvent(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            timestamp_ms=_safe_int(timestamp_value) if timestamp_value is not None else None,
            model_name=str(model_name) if model_name is not None else None,
        )

    model_name_attr = getattr(raw, "model_name", getattr(raw, "model", None))
    timestamp_attr = getattr(raw, "timestamp_ms", None)

    total_tokens_attr = getattr(raw, "total_tokens", None)
    if total_tokens_attr is not None:
        total_tokens = max(0, _safe_int(total_tokens_attr))
        return TokenEvent(
            input_tokens=total_tokens,
            output_tokens=0,
            timestamp_ms=_safe_int(timestamp_attr) if timestamp_attr is not None else None,
            model_name=str(model_name_attr) if model_name_attr is not None else None,
        )

    input_tokens_attr = getattr(raw, "input_tokens", getattr(raw, "input_tokens_est", 0))
    output_tokens_attr = getattr(raw, "output_tokens", getattr(raw, "output_tokens_est", 0))

    return TokenEvent(
        input_tokens=_safe_int(input_tokens_attr),
        output_tokens=_safe_int(output_tokens_attr),
        timestamp_ms=_safe_int(timestamp_attr) if timestamp_attr is not None else None,
        model_name=str(model_name_attr) if model_name_attr is not None else None,
    )


def resolve_model_context_limit(
    model_name: str | None = None,
    *,
    explicit_context_limit: int | None = None,
) -> int:
    """Resolve a model context limit from explicit config or model name."""

    if explicit_context_limit is not None:
        if explicit_context_limit <= 0:
            raise ValueError("explicit_context_limit must be greater than 0")
        return explicit_context_limit

    if model_name is None or not model_name.strip():
        return Defaults.DEFAULT_CONTEXT_LIMIT

    normalised = model_name.lower().strip()

    if normalised in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[normalised]

    if "1m" in normalised or "1000000" in normalised or "1-million" in normalised:
        return 1_000_000

    if "200k" in normalised or "200000" in normalised:
        return 200_000

    return Defaults.DEFAULT_CONTEXT_LIMIT


def estimate_context_tokens(
    events: Sequence[TokenEvent],
    *,
    system_prompt_token_offset: int = Defaults.DEFAULT_SYSTEM_PROMPT_TOKEN_OFFSET,
) -> int:
    """Estimate current context size from token events plus a system prompt offset."""

    if system_prompt_token_offset < 0:
        raise ValueError("system_prompt_token_offset must be greater than or equal to 0")

    return sum(event.total_tokens for event in events) + system_prompt_token_offset


def context_saturation_ratio(context_tokens: int, model_context_limit: int) -> float:
    """Return estimated context saturation ratio."""

    if model_context_limit <= 0:
        raise ValueError("model_context_limit must be greater than 0")

    return max(0, context_tokens) / model_context_limit


def calibrate_context_saturation_score(
    ratio: float,
    *,
    threshold: float = DEFAULT_CONTEXT_SATURATION_THRESHOLD,
) -> float:
    """Convert context saturation ratio into a normalized badness score."""

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")

    if ratio < threshold * 0.75:
        return 0.0
    if ratio < threshold:
        return 0.6
    if ratio < 0.90:
        return 0.8
    if ratio < 1.0:
        return 0.95
    return 1.0


def context_saturation_severity(score: float, *, has_enough_evidence: bool) -> Severity:
    """Map score to severity."""

    if not has_enough_evidence:
        return Severity.INFO
    if score >= 0.90:
        return Severity.CRITICAL
    if score >= 0.60:
        return Severity.WARNING
    return Severity.INFO


def _first_model_name(events: Sequence[TokenEvent]) -> str | None:
    """Return the first non-empty model name in the event stream."""

    for event in events:
        if event.model_name:
            return event.model_name
    return None


def evaluate_context_saturation(
    raw_events: Sequence[TokenEvent | Mapping[str, Any] | object],
    *,
    model_name: str | None = None,
    model_context_limit: int | None = None,
    system_prompt_token_offset: int = Defaults.DEFAULT_SYSTEM_PROMPT_TOKEN_OFFSET,
    threshold: float = DEFAULT_CONTEXT_SATURATION_THRESHOLD,
    min_token_events: int = DEFAULT_MIN_TOKEN_EVENTS,
) -> ContextSaturationResult:
    """Evaluate estimated context saturation for a session."""

    if min_token_events <= 0:
        raise ValueError("min_token_events must be greater than 0")

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")

    events = [normalise_token_event(item) for item in raw_events]
    resolved_model_name = model_name or _first_model_name(events)
    resolved_limit = resolve_model_context_limit(
        resolved_model_name,
        explicit_context_limit=model_context_limit,
    )

    context_tokens = estimate_context_tokens(
        events,
        system_prompt_token_offset=system_prompt_token_offset,
    )
    ratio = context_saturation_ratio(context_tokens, resolved_limit)

    has_enough_evidence = len(events) >= min_token_events

    if not has_enough_evidence:
        score = 0.0
        confidence = len(events) / min_token_events
        explanation = (
            f"Only {len(events)} token event(s) observed; "
            f"need at least {min_token_events} before judging context saturation."
        )
    else:
        score = calibrate_context_saturation_score(ratio, threshold=threshold)
        confidence = 1.0
        explanation = (
            f"Estimated context is {context_tokens} tokens out of {resolved_limit} "
            f"(ratio={ratio:.2f}, threshold>{threshold:.2f})."
        )

    return ContextSaturationResult(
        signal_name=SignalName.CONTEXT_SATURATION,
        score=clamp_score(score),
        confidence=clamp_score(confidence),
        severity=context_saturation_severity(score, has_enough_evidence=has_enough_evidence),
        observed_event_count=len(events),
        context_tokens=context_tokens,
        model_context_limit=resolved_limit,
        saturation_ratio=ratio,
        threshold=threshold,
        system_prompt_token_offset=system_prompt_token_offset,
        min_token_events=min_token_events,
        model_name=resolved_model_name,
        explanation=explanation,
    )


class ContextSaturationSignal:
    """Object-oriented wrapper for context saturation."""

    name = SignalName.CONTEXT_SATURATION

    def __init__(
        self,
        *,
        model_name: str | None = None,
        model_context_limit: int | None = None,
        system_prompt_token_offset: int = Defaults.DEFAULT_SYSTEM_PROMPT_TOKEN_OFFSET,
        threshold: float = DEFAULT_CONTEXT_SATURATION_THRESHOLD,
        min_token_events: int = DEFAULT_MIN_TOKEN_EVENTS,
    ) -> None:
        self.model_name = model_name
        self.model_context_limit = model_context_limit
        self.system_prompt_token_offset = system_prompt_token_offset
        self.threshold = threshold
        self.min_token_events = min_token_events

    def evaluate(
        self,
        raw_events: Sequence[TokenEvent | Mapping[str, Any] | object],
    ) -> ContextSaturationResult:
        """Evaluate this signal against token events."""

        return evaluate_context_saturation(
            raw_events,
            model_name=self.model_name,
            model_context_limit=self.model_context_limit,
            system_prompt_token_offset=self.system_prompt_token_offset,
            threshold=self.threshold,
            min_token_events=self.min_token_events,
        )
