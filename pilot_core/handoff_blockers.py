"""Handoff blocker extraction for Pilot.

Day 45 identifies unresolved blockers, failing loops, and repeated attempts
that should be carried into a handoff summary.

This module is intentionally pure:
- it does not read from the database
- it does not render markdown
- it does not call hooks
- it converts raw session/tool records into HandoffBlocker and HandoffDoNotRedo
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pilot_core.handoff import HandoffBlocker, HandoffBlockerSeverity, HandoffDoNotRedo

DEFAULT_BLOCKER_WINDOW_SIZE = 30
DEFAULT_FAILING_LOOP_THRESHOLD = 3
DEFAULT_REPEATED_ATTEMPT_THRESHOLD = 3
DEFAULT_CRITICAL_LOOP_THRESHOLD = 4
DEFAULT_MAX_BLOCKERS = 5
DEFAULT_MAX_DO_NOT_REDO = 5


@dataclass(frozen=True)
class HandoffAttemptEvent:
    """Normalised tool/session event used by blocker extraction."""

    tool_name: str
    attempt_key: str
    success: bool
    error_text: str = ""
    turn_index: int | None = None
    timestamp_ms: int | None = None
    text: str = ""

    @property
    def failed(self) -> bool:
        """Return True when this event represents a failed attempt."""

        return not self.success


@dataclass(frozen=True)
class FailingLoop:
    """A consecutive loop of failed attempts with the same identity."""

    tool_name: str
    attempt_key: str
    failure_count: int
    first_turn_index: int | None
    last_turn_index: int | None
    evidence: str

    @property
    def is_critical(self) -> bool:
        """Return True when the loop is severe enough for critical severity."""

        return self.failure_count >= DEFAULT_CRITICAL_LOOP_THRESHOLD


@dataclass(frozen=True)
class RepeatedAttempt:
    """A repeated attempt pattern that should not be blindly retried."""

    tool_name: str
    attempt_key: str
    attempt_count: int
    failure_count: int
    evidence: str

    @property
    def has_failures(self) -> bool:
        """Return True when at least one repeated attempt failed."""

        return self.failure_count > 0


@dataclass(frozen=True)
class HandoffBlockerExtraction:
    """Result returned by Day 45 blocker extraction."""

    blockers: tuple[HandoffBlocker, ...]
    do_not_redo: tuple[HandoffDoNotRedo, ...]
    failing_loops: tuple[FailingLoop, ...]
    repeated_attempts: tuple[RepeatedAttempt, ...]
    observed_event_count: int
    failed_event_count: int
    explanation: str

    @property
    def has_blockers(self) -> bool:
        """Return True when blockers were extracted."""

        return bool(self.blockers)

    @property
    def has_do_not_redo_items(self) -> bool:
        """Return True when do-not-redo items were extracted."""

        return bool(self.do_not_redo)


def _record_get(raw: object, key: str, default: object = None) -> object:
    """Read a key from a mapping-like or object-like record."""

    if isinstance(raw, Mapping):
        return raw.get(key, default)

    return getattr(raw, key, default)


def _safe_int_or_none(value: object) -> int | None:
    """Convert a value to int or return None."""

    if value is None:
        return None

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int | float):
        return int(value)

    if isinstance(value, str | bytes | bytearray):
        try:
            return int(value)
        except ValueError:
            return None

    return None


def _stringify_text(value: object) -> str:
    """Convert common payload shapes into compact text."""

    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, Mapping):
        for key in ("message", "error", "text", "content", "stderr", "stdout", "output"):
            nested = value.get(key)
            nested_text = _stringify_text(nested).strip()
            if nested_text:
                return nested_text

        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return str(dict(value))

    if isinstance(value, list | tuple):
        parts = [_stringify_text(item).strip() for item in value]
        return "\n".join(part for part in parts if part)

    return str(value)


def _compact(value: object, *, max_chars: int = 180) -> str:
    """Return a compact stable representation for keys and evidence."""

    text = _stringify_text(value).strip()

    if not text:
        return ""

    text = " ".join(text.split())

    if len(text) <= max_chars:
        return text

    return f"{text[: max_chars - 15]}... [truncated]"


def _json_identity(value: object) -> str:
    """Return a stable JSON-ish identity for a tool input."""

    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        text = repr(value)

    return _compact(text, max_chars=220)


def _normalise_success(raw: object) -> bool:
    """Infer success/failure from common replay and hook payload shapes."""

    success_value = _record_get(raw, "success", None)
    if isinstance(success_value, bool):
        return success_value

    status_value = _record_get(raw, "status", None)
    if isinstance(status_value, str):
        status = status_value.strip().lower()
        if status in {"failed", "failure", "error", "errored"}:
            return False
        if status in {"success", "succeeded", "ok", "passed"}:
            return True

    error_value = _record_get(raw, "error", None)
    return error_value in (None, "", {}, [])


def _extract_tool_name(raw: object) -> str:
    """Extract a tool name from common record shapes."""

    for key in ("tool_name", "tool", "name"):
        value = _record_get(raw, key, None)
        text = _compact(value)
        if text:
            return text

    return "unknown_tool"


def _extract_error_text(raw: object) -> str:
    """Extract useful error text from a record."""

    for key in ("error", "error_message", "stderr", "exception", "failure_reason"):
        value = _record_get(raw, key, None)
        text = _compact(value, max_chars=260)
        if text:
            return text

    if not _normalise_success(raw):
        for key in ("text", "message", "output", "response"):
            value = _record_get(raw, key, None)
            text = _compact(value, max_chars=260)
            if text:
                return text

    return ""


def _extract_text(raw: object) -> str:
    """Extract human-readable text from a raw record."""

    for key in ("text", "message", "content", "response", "assistant_response", "output"):
        value = _record_get(raw, key, None)
        text = _compact(value, max_chars=260)
        if text:
            return text

    return ""


def _nested_mapping(raw: object, key: str) -> Mapping[str, object] | None:
    """Return a nested mapping when available."""

    value = _record_get(raw, key, None)

    if isinstance(value, Mapping):
        return value

    return None


def _extract_attempt_key(raw: object, tool_name: str, error_text: str) -> str:
    """Build a stable identity for a repeated attempt."""

    input_hash = _record_get(raw, "input_hash", None)
    input_hash_text = _compact(input_hash)
    if input_hash_text:
        return f"{tool_name}:hash:{input_hash_text}"

    for key in ("tool_input", "input_payload", "input", "arguments", "params"):
        value = _record_get(raw, key, None)
        if value not in (None, ""):
            return f"{tool_name}:input:{_json_identity(value)}"

    for nested_key in ("tool_input", "input_payload", "input"):
        nested = _nested_mapping(raw, nested_key)
        if nested is None:
            continue

        for key in ("command", "file_path", "path", "query"):
            value = nested.get(key)
            value_text = _compact(value)
            if value_text:
                return f"{tool_name}:{key}:{value_text}"

    for key in ("command", "file_path", "path", "query"):
        value = _record_get(raw, key, None)
        value_text = _compact(value)
        if value_text:
            return f"{tool_name}:{key}:{value_text}"

    if error_text:
        return f"{tool_name}:error:{_compact(error_text)}"

    return f"{tool_name}:unknown"


def normalise_handoff_attempt_event(
    raw: HandoffAttemptEvent | Mapping[str, Any] | object,
) -> HandoffAttemptEvent:
    """Convert a raw hook/replay record into HandoffAttemptEvent."""

    if isinstance(raw, HandoffAttemptEvent):
        return raw

    tool_name = _extract_tool_name(raw)
    success = _normalise_success(raw)
    error_text = _extract_error_text(raw)
    attempt_key = _extract_attempt_key(raw, tool_name, error_text)

    return HandoffAttemptEvent(
        tool_name=tool_name,
        attempt_key=attempt_key,
        success=success,
        error_text=error_text,
        turn_index=_safe_int_or_none(_record_get(raw, "turn_index", None)),
        timestamp_ms=_safe_int_or_none(_record_get(raw, "timestamp_ms", None)),
        text=_extract_text(raw),
    )


def recent_handoff_attempt_events(
    raw_records: Sequence[HandoffAttemptEvent | Mapping[str, Any] | object],
    *,
    window_size: int = DEFAULT_BLOCKER_WINDOW_SIZE,
) -> tuple[HandoffAttemptEvent, ...]:
    """Return normalised recent attempt events."""

    if window_size <= 0:
        raise ValueError("window_size must be greater than 0")

    records = list(raw_records[-window_size:])
    return tuple(normalise_handoff_attempt_event(record) for record in records)


def _turn_span(events: Sequence[HandoffAttemptEvent]) -> tuple[int | None, int | None]:
    """Return first and last known turn index for a sequence."""

    turn_indexes = [event.turn_index for event in events if event.turn_index is not None]

    if not turn_indexes:
        return None, None

    return min(turn_indexes), max(turn_indexes)


def _loop_evidence(events: Sequence[HandoffAttemptEvent]) -> str:
    """Return compact evidence for a failing loop."""

    error_texts = [event.error_text for event in events if event.error_text.strip()]
    if error_texts:
        return _compact(error_texts[-1], max_chars=260)

    return f"{len(events)} consecutive failed attempt(s)"


def _build_failing_loop(events: Sequence[HandoffAttemptEvent]) -> FailingLoop:
    """Build a FailingLoop from a non-empty failed segment."""

    first_turn, last_turn = _turn_span(events)
    latest = events[-1]

    return FailingLoop(
        tool_name=latest.tool_name,
        attempt_key=latest.attempt_key,
        failure_count=len(events),
        first_turn_index=first_turn,
        last_turn_index=last_turn,
        evidence=_loop_evidence(events),
    )


def find_failing_loops(
    events: Sequence[HandoffAttemptEvent],
    *,
    threshold: int = DEFAULT_FAILING_LOOP_THRESHOLD,
) -> tuple[FailingLoop, ...]:
    """Find consecutive failed attempts with the same attempt identity."""

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")

    loops: list[FailingLoop] = []
    current_segment: list[HandoffAttemptEvent] = []

    def flush_segment() -> None:
        if len(current_segment) >= threshold:
            loops.append(_build_failing_loop(current_segment))
        current_segment.clear()

    for event in events:
        if not event.failed:
            flush_segment()
            continue

        if not current_segment:
            current_segment.append(event)
            continue

        if current_segment[-1].attempt_key == event.attempt_key:
            current_segment.append(event)
            continue

        flush_segment()
        current_segment.append(event)

    flush_segment()

    return tuple(
        sorted(
            loops,
            key=lambda loop: (loop.failure_count, loop.last_turn_index or -1),
            reverse=True,
        )
    )


def find_repeated_attempts(
    events: Sequence[HandoffAttemptEvent],
    *,
    threshold: int = DEFAULT_REPEATED_ATTEMPT_THRESHOLD,
) -> tuple[RepeatedAttempt, ...]:
    """Find repeated attempts that included at least one failure."""

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")

    grouped: dict[str, list[HandoffAttemptEvent]] = {}

    for event in events:
        grouped.setdefault(event.attempt_key, []).append(event)

    repeated: list[RepeatedAttempt] = []

    for attempt_key, grouped_events in grouped.items():
        attempt_count = len(grouped_events)
        failed_events = [event for event in grouped_events if event.failed]

        if attempt_count < threshold or not failed_events:
            continue

        latest = grouped_events[-1]
        repeated.append(
            RepeatedAttempt(
                tool_name=latest.tool_name,
                attempt_key=attempt_key,
                attempt_count=attempt_count,
                failure_count=len(failed_events),
                evidence=_loop_evidence(failed_events),
            )
        )

    return tuple(
        sorted(
            repeated,
            key=lambda attempt: (attempt.failure_count, attempt.attempt_count),
            reverse=True,
        )
    )


def _blocker_from_failing_loop(loop: FailingLoop) -> HandoffBlocker:
    """Convert a failing loop into a handoff blocker."""

    severity = HandoffBlockerSeverity.CRITICAL if loop.is_critical else HandoffBlockerSeverity.ERROR

    return HandoffBlocker(
        description=(
            f"Failing loop detected in {loop.tool_name}: "
            f"{loop.failure_count} consecutive failed attempt(s)."
        ),
        severity=severity,
        evidence=loop.evidence,
    )


def _blocker_from_repeated_attempt(attempt: RepeatedAttempt) -> HandoffBlocker:
    """Convert a repeated attempt into a handoff blocker."""

    severity = (
        HandoffBlockerSeverity.ERROR
        if attempt.failure_count >= DEFAULT_FAILING_LOOP_THRESHOLD
        else HandoffBlockerSeverity.WARNING
    )

    return HandoffBlocker(
        description=(
            f"Repeated attempt detected in {attempt.tool_name}: "
            f"{attempt.attempt_count} attempt(s), {attempt.failure_count} failure(s)."
        ),
        severity=severity,
        evidence=attempt.evidence,
    )


def _do_not_redo_from_failing_loop(loop: FailingLoop) -> HandoffDoNotRedo:
    """Convert a failing loop into a do-not-redo item."""

    return HandoffDoNotRedo(
        item=f"Do not blindly retry {loop.tool_name} with the same failing input.",
        reason=(
            f"The same attempt failed {loop.failure_count} consecutive time(s). "
            f"Evidence: {loop.evidence}"
        ),
    )


def _do_not_redo_from_repeated_attempt(attempt: RepeatedAttempt) -> HandoffDoNotRedo:
    """Convert a repeated attempt into a do-not-redo item."""

    return HandoffDoNotRedo(
        item=f"Do not repeat {attempt.tool_name} with the same attempt identity.",
        reason=(
            f"The attempt appeared {attempt.attempt_count} time(s) and failed "
            f"{attempt.failure_count} time(s). Evidence: {attempt.evidence}"
        ),
    )


def extract_handoff_blockers(
    raw_records: Sequence[HandoffAttemptEvent | Mapping[str, Any] | object],
    *,
    window_size: int = DEFAULT_BLOCKER_WINDOW_SIZE,
    failing_loop_threshold: int = DEFAULT_FAILING_LOOP_THRESHOLD,
    repeated_attempt_threshold: int = DEFAULT_REPEATED_ATTEMPT_THRESHOLD,
    max_blockers: int = DEFAULT_MAX_BLOCKERS,
    max_do_not_redo: int = DEFAULT_MAX_DO_NOT_REDO,
) -> HandoffBlockerExtraction:
    """Extract blockers and do-not-redo items from session records."""

    if max_blockers <= 0:
        raise ValueError("max_blockers must be greater than 0")
    if max_do_not_redo <= 0:
        raise ValueError("max_do_not_redo must be greater than 0")

    events = recent_handoff_attempt_events(raw_records, window_size=window_size)
    failed_event_count = sum(1 for event in events if event.failed)

    failing_loops = find_failing_loops(
        events,
        threshold=failing_loop_threshold,
    )
    repeated_attempts = find_repeated_attempts(
        events,
        threshold=repeated_attempt_threshold,
    )

    blockers: list[HandoffBlocker] = []
    do_not_redo: list[HandoffDoNotRedo] = []
    seen_blocker_descriptions: set[str] = set()
    seen_do_not_redo_items: set[str] = set()

    def add_blocker(blocker: HandoffBlocker) -> None:
        if blocker.description in seen_blocker_descriptions:
            return
        if len(blockers) >= max_blockers:
            return

        seen_blocker_descriptions.add(blocker.description)
        blockers.append(blocker)

    def add_do_not_redo(item: HandoffDoNotRedo) -> None:
        if item.item in seen_do_not_redo_items:
            return
        if len(do_not_redo) >= max_do_not_redo:
            return

        seen_do_not_redo_items.add(item.item)
        do_not_redo.append(item)

    for loop in failing_loops:
        add_blocker(_blocker_from_failing_loop(loop))
        add_do_not_redo(_do_not_redo_from_failing_loop(loop))

    for attempt in repeated_attempts:
        add_blocker(_blocker_from_repeated_attempt(attempt))
        add_do_not_redo(_do_not_redo_from_repeated_attempt(attempt))

    if not blockers and failed_event_count >= failing_loop_threshold:
        add_blocker(
            HandoffBlocker(
                description=(
                    f"Failure density detected: {failed_event_count} failed event(s) "
                    f"in the last {len(events)} observed event(s)."
                ),
                severity=HandoffBlockerSeverity.WARNING,
                evidence="Failures did not form one repeated loop, but the session still has unresolved failures.",
            )
        )

    explanation = (
        f"Observed {len(events)} event(s), {failed_event_count} failed event(s), "
        f"{len(failing_loops)} failing loop(s), and "
        f"{len(repeated_attempts)} repeated attempt pattern(s)."
    )

    return HandoffBlockerExtraction(
        blockers=tuple(blockers),
        do_not_redo=tuple(do_not_redo),
        failing_loops=failing_loops,
        repeated_attempts=repeated_attempts,
        observed_event_count=len(events),
        failed_event_count=failed_event_count,
        explanation=explanation,
    )


def handoff_blocker_extraction_summary(
    result: HandoffBlockerExtraction,
) -> dict[str, object]:
    """Return a compact serialisable summary for smoke scripts and future CLI."""

    return {
        "observed_event_count": result.observed_event_count,
        "failed_event_count": result.failed_event_count,
        "blocker_count": len(result.blockers),
        "do_not_redo_count": len(result.do_not_redo),
        "failing_loop_count": len(result.failing_loops),
        "repeated_attempt_count": len(result.repeated_attempts),
        "has_blockers": result.has_blockers,
        "has_do_not_redo_items": result.has_do_not_redo_items,
        "blockers": [blocker.to_dict() for blocker in result.blockers],
        "do_not_redo": [item.to_dict() for item in result.do_not_redo],
        "explanation": result.explanation,
    }
