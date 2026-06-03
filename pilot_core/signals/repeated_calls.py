"""Pilot module placeholder."""


# Day 27 public compatibility API.
#
# Earlier repeated-calls work may expose a class-based API. Day 27 hardening
# needs a stable function entrypoint matching the other signal modules:
# evaluate_error_cascade, evaluate_token_burn, and evaluate_context_saturation.
def _pilot_day27_record_get(raw: object, key: str, default: object = None) -> object:
    """Read a key from a dict-like or object-like record."""

    if isinstance(raw, dict):
        return raw.get(key, default)

    return getattr(raw, key, default)


def _pilot_day27_call_key(raw: object) -> str:
    """Build the repeated-call identity from tool name and input hash/payload."""

    import json

    tool_name = _pilot_day27_record_get(raw, "tool_name", "")

    input_hash = _pilot_day27_record_get(raw, "input_hash", None)
    if input_hash not in (None, ""):
        return f"{tool_name}:{input_hash}"

    payload = _pilot_day27_record_get(raw, "input_payload", None)
    if payload is None:
        payload = _pilot_day27_record_get(raw, "tool_input", None)
    if payload is None:
        payload = _pilot_day27_record_get(raw, "input", "")

    try:
        payload_text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        payload_text = repr(payload)

    return f"{tool_name}:{payload_text}"


def evaluate_repeated_calls(
    raw_calls: list[object] | tuple[object, ...],
    *,
    window_size: int = 10,
    repeat_threshold: int = 3,
) -> object:
    """Evaluate repeated tool calls using the shared Day 27 signal contract.

    The signal identity is based on:

    - tool_name
    - input_hash when available
    - otherwise a stable representation of input_payload/tool_input/input
    """

    from types import SimpleNamespace

    from pilot_core.constants import Severity, SignalName

    if window_size <= 0:
        raise ValueError("window_size must be greater than 0")
    if repeat_threshold <= 0:
        raise ValueError("repeat_threshold must be greater than 0")

    recent_calls = list(raw_calls[-window_size:])

    counts: dict[str, int] = {}
    for item in recent_calls:
        call_key = _pilot_day27_call_key(item)
        counts[call_key] = counts.get(call_key, 0) + 1

    if counts:
        repeated_key = max(counts, key=lambda key: counts[key])
        repeated_call_count = counts[repeated_key]
    else:
        repeated_key = None
        repeated_call_count = 0

    if repeated_call_count < 2:
        score = 0.0
    elif repeated_call_count == 2:
        score = 0.3
    elif repeated_call_count == 3:
        score = 0.6
    else:
        score = 0.9

    fired = repeated_call_count >= repeat_threshold
    confidence = min(1.0, len(recent_calls) / max(1, repeat_threshold))

    if score >= 0.9:
        severity = Severity.CRITICAL
    elif score >= 0.6:
        severity = Severity.WARNING
    else:
        severity = Severity.INFO

    explanation = (
        f"Most repeated tool call appeared {repeated_call_count} time(s) "
        f"inside the last {window_size} call(s) "
        f"(threshold>={repeat_threshold})."
    )

    return SimpleNamespace(
        signal_name=SignalName.REPEATED_CALLS,
        score=score,
        confidence=confidence,
        severity=severity,
        window_size=window_size,
        observed_call_count=len(recent_calls),
        repeated_call_count=repeated_call_count,
        repeat_threshold=repeat_threshold,
        repeated_key=repeated_key,
        explanation=explanation,
        fired=fired,
    )
