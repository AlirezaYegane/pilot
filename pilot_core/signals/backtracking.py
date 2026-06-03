"""Backtracking degradation signal.

This signal detects repeated edits to the same file without user feedback
between those edits.

Default policy:
- track edit events by normalised file path
- count repeated edits to a file already edited in the recent turn window
- ignore recurrence when a user-feedback event happened between the edits
- fire when backtrack_count >= 2
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pilot_core.constants import Severity, SignalName

DEFAULT_BACKTRACKING_LOOKBACK_TURNS = 3
DEFAULT_BACKTRACKING_THRESHOLD = 2
DEFAULT_MIN_EDIT_EVENTS = 2

EDIT_TOOL_NAMES = frozenset({"Edit", "MultiEdit", "Write"})


class BacktrackingEventKind(str, Enum):
    """Normalised event kind used by the backtracking signal."""

    EDIT = "edit"
    USER_FEEDBACK = "user_feedback"
    OTHER = "other"


@dataclass(frozen=True)
class BacktrackingEvent:
    """Minimal event used to detect file-edit backtracking."""

    kind: BacktrackingEventKind
    turn_index: int
    file_path: str | None = None
    tool_name: str | None = None
    timestamp_ms: int | None = None


@dataclass(frozen=True)
class BacktrackingResult:
    """Result returned by the backtracking signal."""

    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    observed_event_count: int
    edit_event_count: int
    backtrack_count: int
    repeated_files: tuple[str, ...]
    lookback_turns: int
    threshold: int
    min_edit_events: int
    explanation: str

    @property
    def fired(self) -> bool:
        """Return True when repeated edits are strong enough to count as fired."""

        has_enough_edits = self.edit_event_count >= self.min_edit_events
        return has_enough_edits and self.backtrack_count >= self.threshold


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


def normalise_file_path(value: object, *, case_insensitive: bool = True) -> str | None:
    """Return a stable file-path identity for repeated edit detection."""

    if value in (None, ""):
        return None

    path = str(value).strip().replace("\\", "/")
    while "//" in path:
        path = path.replace("//", "/")

    if not path:
        return None

    return path.lower() if case_insensitive else path


def _nested_mapping(raw: object, key: str) -> Mapping[str, object] | None:
    """Return a nested mapping from a dict/object record when available."""

    value = _record_get(raw, key, None)
    if isinstance(value, Mapping):
        return value

    return None


def extract_file_path(raw: object, *, case_insensitive: bool = True) -> str | None:
    """Extract an edited file path from common hook/test payload shapes."""

    for key in ("file_path", "path", "filepath", "target_file"):
        value = _record_get(raw, key, None)
        path = normalise_file_path(value, case_insensitive=case_insensitive)
        if path is not None:
            return path

    for nested_key in ("tool_input", "input_payload", "input"):
        nested = _nested_mapping(raw, nested_key)
        if nested is None:
            continue

        for key in ("file_path", "path", "filepath", "target_file"):
            value = nested.get(key)
            path = normalise_file_path(value, case_insensitive=case_insensitive)
            if path is not None:
                return path

    return None


def _normalise_event_kind(raw: object, file_path: str | None) -> BacktrackingEventKind:
    """Infer event kind from explicit metadata, role, tool name, or file path."""

    explicit_kind = _record_get(raw, "kind", None)
    if explicit_kind is None:
        explicit_kind = _record_get(raw, "event_type", None)

    if explicit_kind is not None:
        raw_kind = str(explicit_kind).strip().lower()
        if raw_kind in {"user_feedback", "user_prompt", "user_prompt_submit", "feedback"}:
            return BacktrackingEventKind.USER_FEEDBACK
        if raw_kind in {"edit", "file_edit", "tool_edit"}:
            return BacktrackingEventKind.EDIT

    role = _record_get(raw, "role", None)
    if role is not None and str(role).strip().lower() == "user":
        return BacktrackingEventKind.USER_FEEDBACK

    tool_name = _record_get(raw, "tool_name", None)
    if tool_name is not None and str(tool_name) in EDIT_TOOL_NAMES:
        return BacktrackingEventKind.EDIT

    if file_path is not None:
        return BacktrackingEventKind.EDIT

    return BacktrackingEventKind.OTHER


def normalise_backtracking_event(
    raw: BacktrackingEvent | Mapping[str, Any] | object,
    *,
    case_insensitive_paths: bool = True,
) -> BacktrackingEvent:
    """Convert a dict/object/hook record into BacktrackingEvent."""

    if isinstance(raw, BacktrackingEvent):
        return raw

    file_path = extract_file_path(raw, case_insensitive=case_insensitive_paths)
    kind = _normalise_event_kind(raw, file_path)

    tool_name_value = _record_get(raw, "tool_name", None)
    timestamp_value = _record_get(raw, "timestamp_ms", None)
    turn_index_value = _record_get(raw, "turn_index", 0)

    return BacktrackingEvent(
        kind=kind,
        turn_index=_safe_int(turn_index_value),
        file_path=file_path,
        tool_name=str(tool_name_value) if tool_name_value is not None else None,
        timestamp_ms=_safe_int(timestamp_value) if timestamp_value is not None else None,
    )


def has_user_feedback_between(
    events: Sequence[BacktrackingEvent],
    *,
    previous_index: int,
    current_index: int,
) -> bool:
    """Return True if user feedback exists between two event indexes."""

    if previous_index >= current_index:
        return False

    between = events[previous_index + 1 : current_index]
    return any(event.kind is BacktrackingEventKind.USER_FEEDBACK for event in between)


def count_backtracking_edits(
    events: Sequence[BacktrackingEvent],
    *,
    lookback_turns: int = DEFAULT_BACKTRACKING_LOOKBACK_TURNS,
) -> tuple[int, tuple[str, ...]]:
    """Count repeated file edits without user feedback in the lookback window."""

    if lookback_turns <= 0:
        raise ValueError("lookback_turns must be greater than 0")

    backtrack_count = 0
    repeated_files: set[str] = set()

    edit_indexes = [
        index
        for index, event in enumerate(events)
        if event.kind is BacktrackingEventKind.EDIT and event.file_path is not None
    ]

    for current_index in edit_indexes:
        current = events[current_index]
        if current.file_path is None:
            continue

        for previous_index in reversed(edit_indexes):
            if previous_index >= current_index:
                continue

            previous = events[previous_index]
            if previous.file_path != current.file_path:
                continue

            turn_delta = current.turn_index - previous.turn_index
            if turn_delta < 0:
                turn_delta = 0

            if turn_delta > lookback_turns:
                break

            if has_user_feedback_between(
                events,
                previous_index=previous_index,
                current_index=current_index,
            ):
                continue

            backtrack_count += 1
            repeated_files.add(current.file_path)
            break

    return backtrack_count, tuple(sorted(repeated_files))


def calibrate_backtracking_score(
    backtrack_count: int,
    *,
    threshold: int = DEFAULT_BACKTRACKING_THRESHOLD,
) -> float:
    """Convert backtrack count into a normalized badness score."""

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0")

    if backtrack_count <= 0:
        return 0.0
    if backtrack_count < threshold:
        return 0.4
    if backtrack_count == threshold:
        return 0.7
    return 0.95


def backtracking_severity(score: float, *, has_enough_evidence: bool) -> Severity:
    """Map score and evidence size to severity."""

    if not has_enough_evidence:
        return Severity.INFO
    if score >= 0.90:
        return Severity.CRITICAL
    if score >= 0.60:
        return Severity.WARNING
    return Severity.INFO


def evaluate_backtracking(
    raw_events: Sequence[BacktrackingEvent | Mapping[str, Any] | object],
    *,
    lookback_turns: int = DEFAULT_BACKTRACKING_LOOKBACK_TURNS,
    threshold: int = DEFAULT_BACKTRACKING_THRESHOLD,
    min_edit_events: int = DEFAULT_MIN_EDIT_EVENTS,
    case_insensitive_paths: bool = True,
) -> BacktrackingResult:
    """Evaluate the backtracking signal for recent hook/tool/user events."""

    if min_edit_events <= 0:
        raise ValueError("min_edit_events must be greater than 0")

    events = [
        normalise_backtracking_event(item, case_insensitive_paths=case_insensitive_paths)
        for item in raw_events
    ]

    edit_event_count = sum(1 for event in events if event.kind is BacktrackingEventKind.EDIT)

    if edit_event_count < min_edit_events:
        score = 0.0
        confidence = edit_event_count / min_edit_events
        backtrack_count = 0
        repeated_files: tuple[str, ...] = tuple()
        explanation = (
            f"Only {edit_event_count} edit event(s) observed; "
            f"need at least {min_edit_events} before judging backtracking."
        )
    else:
        backtrack_count, repeated_files = count_backtracking_edits(
            events,
            lookback_turns=lookback_turns,
        )
        score = calibrate_backtracking_score(backtrack_count, threshold=threshold)
        confidence = 1.0
        files_text = ", ".join(repeated_files) if repeated_files else "none"
        explanation = (
            f"Detected {backtrack_count} repeated edit(s) to recently edited files "
            f"inside the last {lookback_turns} turn(s) without user feedback "
            f"(threshold>={threshold}, files={files_text})."
        )

    has_enough_evidence = edit_event_count >= min_edit_events

    return BacktrackingResult(
        signal_name=SignalName.BACKTRACKING,
        score=clamp_score(score),
        confidence=clamp_score(confidence),
        severity=backtracking_severity(score, has_enough_evidence=has_enough_evidence),
        observed_event_count=len(events),
        edit_event_count=edit_event_count,
        backtrack_count=backtrack_count,
        repeated_files=repeated_files,
        lookback_turns=lookback_turns,
        threshold=threshold,
        min_edit_events=min_edit_events,
        explanation=explanation,
    )


class BacktrackingSignal:
    """Object-oriented wrapper for the backtracking signal."""

    name = SignalName.BACKTRACKING

    def __init__(
        self,
        *,
        lookback_turns: int = DEFAULT_BACKTRACKING_LOOKBACK_TURNS,
        threshold: int = DEFAULT_BACKTRACKING_THRESHOLD,
        min_edit_events: int = DEFAULT_MIN_EDIT_EVENTS,
        case_insensitive_paths: bool = True,
    ) -> None:
        self.lookback_turns = lookback_turns
        self.threshold = threshold
        self.min_edit_events = min_edit_events
        self.case_insensitive_paths = case_insensitive_paths

    def evaluate(
        self,
        raw_events: Sequence[BacktrackingEvent | Mapping[str, Any] | object],
    ) -> BacktrackingResult:
        """Evaluate this signal against recent events."""

        return evaluate_backtracking(
            raw_events,
            lookback_turns=self.lookback_turns,
            threshold=self.threshold,
            min_edit_events=self.min_edit_events,
            case_insensitive_paths=self.case_insensitive_paths,
        )
