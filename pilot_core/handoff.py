"""Handoff schema for Pilot.

Day 43 defines the stable data contract for handoff summaries.

This module intentionally does not extract information from storage and does
not render markdown yet. Later days will use this schema for:

- DB summary extraction
- blocker extraction
- markdown rendering
- stop-hook handoff generation
- session-start resume flow
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

HANDOFF_SCHEMA_VERSION = "1.0"


class HandoffFileStatus(str, Enum):
    """Status of a file mentioned in a handoff."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    UNKNOWN = "unknown"


class HandoffBlockerSeverity(str, Enum):
    """Severity for a blocker captured in a handoff."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class HandoffFileChange:
    """A file changed or inspected during the session."""

    path: str
    status: HandoffFileStatus = HandoffFileStatus.MODIFIED
    reason: str = ""
    important: bool = True

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation."""

        return {
            "path": self.path,
            "status": self.status.value,
            "reason": self.reason,
            "important": self.important,
        }


@dataclass(frozen=True)
class HandoffDecision:
    """A decision that should be preserved for the next session."""

    title: str
    rationale: str = ""
    alternatives_rejected: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation."""

        return {
            "title": self.title,
            "rationale": self.rationale,
            "alternatives_rejected": list(self.alternatives_rejected),
        }


@dataclass(frozen=True)
class HandoffBlocker:
    """A blocker or unresolved issue that needs attention."""

    description: str
    severity: HandoffBlockerSeverity = HandoffBlockerSeverity.WARNING
    evidence: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation."""

        return {
            "description": self.description,
            "severity": self.severity.value,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class HandoffDoNotRedo:
    """A failed attempt that should not be repeated blindly."""

    item: str
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation."""

        return {
            "item": self.item,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class HandoffSchema:
    """Stable handoff summary data model."""

    task: str
    progress: str
    next_step: str
    session_id: str | None = None
    generated_at: str = ""
    schema_version: str = HANDOFF_SCHEMA_VERSION
    decisions: tuple[HandoffDecision, ...] = field(default_factory=tuple)
    files_modified: tuple[HandoffFileChange, ...] = field(default_factory=tuple)
    blockers: tuple[HandoffBlocker, ...] = field(default_factory=tuple)
    do_not_redo: tuple[HandoffDoNotRedo, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Fill generated_at when omitted."""

        if not self.generated_at:
            object.__setattr__(self, "generated_at", utc_now_iso())

    @property
    def has_blockers(self) -> bool:
        """Return True when unresolved blockers are present."""

        return bool(self.blockers)

    @property
    def has_do_not_redo_items(self) -> bool:
        """Return True when failed attempts were recorded."""

        return bool(self.do_not_redo)

    def validation_errors(self) -> tuple[str, ...]:
        """Return schema validation errors without raising."""

        errors: list[str] = []

        if not self.task.strip():
            errors.append("task is required")
        if not self.progress.strip():
            errors.append("progress is required")
        if not self.next_step.strip():
            errors.append("next_step is required")
        if not self.schema_version.strip():
            errors.append("schema_version is required")

        for index, decision in enumerate(self.decisions):
            if not decision.title.strip():
                errors.append(f"decisions[{index}].title is required")

        for index, file_change in enumerate(self.files_modified):
            if not file_change.path.strip():
                errors.append(f"files_modified[{index}].path is required")

        for index, blocker in enumerate(self.blockers):
            if not blocker.description.strip():
                errors.append(f"blockers[{index}].description is required")

        for index, item in enumerate(self.do_not_redo):
            if not item.item.strip():
                errors.append(f"do_not_redo[{index}].item is required")

        return tuple(errors)

    def is_valid(self) -> bool:
        """Return True when the schema has no validation errors."""

        return not self.validation_errors()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation."""

        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "generated_at": self.generated_at,
            "task": self.task,
            "progress": self.progress,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "files_modified": [file_change.to_dict() for file_change in self.files_modified],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "next_step": self.next_step,
            "do_not_redo": [item.to_dict() for item in self.do_not_redo],
            "notes": list(self.notes),
        }


def utc_now_iso() -> str:
    """Return a UTC ISO timestamp."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_str(value: object, *, default: str = "") -> str:
    """Return value as string with a safe default."""

    if value is None:
        return default

    return str(value)


def _as_bool(value: object, *, default: bool = False) -> bool:
    """Return value as bool with a safe default."""

    if isinstance(value, bool):
        return value

    if value is None:
        return default

    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}

    return bool(value)


def _as_mapping(value: object) -> Mapping[str, object]:
    """Return a mapping or an empty mapping."""

    if isinstance(value, Mapping):
        return value

    return {}


def _as_sequence(value: object) -> Sequence[object]:
    """Return a sequence suitable for normalisation."""

    if isinstance(value, str):
        return [value]

    if isinstance(value, Sequence):
        return value

    return []


def _parse_file_status(value: object) -> HandoffFileStatus:
    """Parse file status from string or enum."""

    if isinstance(value, HandoffFileStatus):
        return value

    raw = _as_str(value, default=HandoffFileStatus.UNKNOWN.value)

    try:
        return HandoffFileStatus(raw)
    except ValueError:
        return HandoffFileStatus.UNKNOWN


def _parse_blocker_severity(value: object) -> HandoffBlockerSeverity:
    """Parse blocker severity from string or enum."""

    if isinstance(value, HandoffBlockerSeverity):
        return value

    raw = _as_str(value, default=HandoffBlockerSeverity.WARNING.value)

    try:
        return HandoffBlockerSeverity(raw)
    except ValueError:
        return HandoffBlockerSeverity.WARNING


def handoff_file_change_from_dict(raw: Mapping[str, object]) -> HandoffFileChange:
    """Build a file-change record from a dictionary."""

    return HandoffFileChange(
        path=_as_str(raw.get("path")),
        status=_parse_file_status(raw.get("status")),
        reason=_as_str(raw.get("reason")),
        important=_as_bool(raw.get("important"), default=True),
    )


def handoff_decision_from_dict(raw: Mapping[str, object]) -> HandoffDecision:
    """Build a decision record from a dictionary."""

    alternatives = tuple(
        _as_str(item)
        for item in _as_sequence(raw.get("alternatives_rejected"))
        if _as_str(item).strip()
    )

    return HandoffDecision(
        title=_as_str(raw.get("title")),
        rationale=_as_str(raw.get("rationale")),
        alternatives_rejected=alternatives,
    )


def handoff_blocker_from_dict(raw: Mapping[str, object]) -> HandoffBlocker:
    """Build a blocker record from a dictionary."""

    return HandoffBlocker(
        description=_as_str(raw.get("description")),
        severity=_parse_blocker_severity(raw.get("severity")),
        evidence=_as_str(raw.get("evidence")),
    )


def handoff_do_not_redo_from_dict(raw: Mapping[str, object]) -> HandoffDoNotRedo:
    """Build a do-not-redo record from a dictionary."""

    return HandoffDoNotRedo(
        item=_as_str(raw.get("item")),
        reason=_as_str(raw.get("reason")),
    )


def handoff_from_dict(raw: Mapping[str, object]) -> HandoffSchema:
    """Build a handoff schema from a dictionary."""

    decisions = tuple(
        handoff_decision_from_dict(_as_mapping(item)) for item in _as_sequence(raw.get("decisions"))
    )
    files_modified = tuple(
        handoff_file_change_from_dict(_as_mapping(item))
        for item in _as_sequence(raw.get("files_modified"))
    )
    blockers = tuple(
        handoff_blocker_from_dict(_as_mapping(item)) for item in _as_sequence(raw.get("blockers"))
    )
    do_not_redo = tuple(
        handoff_do_not_redo_from_dict(_as_mapping(item))
        for item in _as_sequence(raw.get("do_not_redo"))
    )
    notes = tuple(_as_str(item) for item in _as_sequence(raw.get("notes")) if _as_str(item).strip())

    return HandoffSchema(
        schema_version=_as_str(raw.get("schema_version"), default=HANDOFF_SCHEMA_VERSION),
        session_id=(_as_str(raw.get("session_id")) if raw.get("session_id") is not None else None),
        generated_at=_as_str(raw.get("generated_at")),
        task=_as_str(raw.get("task")),
        progress=_as_str(raw.get("progress")),
        decisions=decisions,
        files_modified=files_modified,
        blockers=blockers,
        next_step=_as_str(raw.get("next_step")),
        do_not_redo=do_not_redo,
        notes=notes,
    )


def handoff_to_json(handoff: HandoffSchema, *, indent: int | None = 2) -> str:
    """Serialise a handoff schema to JSON."""

    return json.dumps(
        handoff.to_dict(),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
    )


def handoff_from_json(text: str) -> HandoffSchema:
    """Parse a handoff schema from JSON text."""

    raw = json.loads(text)

    if not isinstance(raw, Mapping):
        raise ValueError("handoff JSON must contain an object")

    return handoff_from_dict(raw)


def create_empty_handoff(
    *,
    task: str,
    progress: str,
    next_step: str,
    session_id: str | None = None,
) -> HandoffSchema:
    """Create the smallest valid handoff schema."""

    return HandoffSchema(
        session_id=session_id,
        task=task,
        progress=progress,
        next_step=next_step,
    )


def handoff_summary(handoff: HandoffSchema) -> dict[str, object]:
    """Return a compact summary for smoke scripts and future CLI."""

    return {
        "schema_version": handoff.schema_version,
        "session_id": handoff.session_id,
        "task": handoff.task,
        "progress": handoff.progress,
        "decision_count": len(handoff.decisions),
        "file_count": len(handoff.files_modified),
        "blocker_count": len(handoff.blockers),
        "do_not_redo_count": len(handoff.do_not_redo),
        "has_blockers": handoff.has_blockers,
        "is_valid": handoff.is_valid(),
        "validation_errors": list(handoff.validation_errors()),
        "next_step": handoff.next_step,
    }
