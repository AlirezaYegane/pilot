"""Session list and detail renderers for Pilot CLI.

Day 53 adds the rendering layer used by:
- pilot sessions
- pilot show <session_id>

This module is intentionally pure:
- it does not read SQLite
- it does not print
- it does not call hooks
- it only normalises records and renders deterministic text
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pilot_core.constants import (
    SessionState,
    SignalName,
    parse_session_state,
    parse_signal_name,
)

DEFAULT_SESSION_LIST_LIMIT = 20
DEFAULT_MAX_DETAIL_ITEMS = 12
DEFAULT_MAX_TEXT_CHARS = 240


@dataclass(frozen=True)
class SessionListItem:
    """One row in the session list view."""

    session_id: str
    state: SessionState = SessionState.HEALTHY
    health_score: float | None = None
    started_at_ms: int | None = None
    ended_at_ms: int | None = None
    updated_at_ms: int | None = None
    tool_call_count: int = 0
    signal_count: int = 0
    total_tokens: int = 0
    handoff_summary_path: str | None = None

    @property
    def is_open(self) -> bool:
        """Return True when the session has no end timestamp."""

        return self.ended_at_ms is None

    @property
    def display_health(self) -> str:
        """Return compact health text."""

        if self.health_score is None:
            return "-"

        return f"{_clamp_score(self.health_score):.2f}"


@dataclass(frozen=True)
class SessionSignalItem:
    """Signal row shown in session detail."""

    signal_name: SignalName
    score: float
    confidence: float = 1.0
    fired: bool = False
    explanation: str = ""
    timestamp_ms: int | None = None


@dataclass(frozen=True)
class SessionToolUseItem:
    """Tool-use row shown in session detail."""

    tool_name: str
    success: bool = True
    timestamp_ms: int | None = None
    total_tokens: int = 0
    error_text: str = ""
    input_hash: str = ""


@dataclass(frozen=True)
class SessionDetail:
    """Complete detail view for one session."""

    session: SessionListItem
    signals: tuple[SessionSignalItem, ...] = tuple()
    tools: tuple[SessionToolUseItem, ...] = tuple()
    handoff_path: str | None = None
    notes: tuple[str, ...] = tuple()


def _record_get(raw: object, key: str, default: object = None) -> object:
    """Read a value from a mapping-like or object-like record."""

    if isinstance(raw, Mapping):
        return raw.get(key, default)

    return getattr(raw, key, default)


def _safe_int(value: object, *, default: int = 0) -> int:
    """Convert value to int safely."""

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


def _safe_optional_int(value: object) -> int | None:
    """Convert value to optional int safely."""

    if value in (None, ""):
        return None

    return _safe_int(value)


def _safe_float(value: object, *, default: float = 0.0) -> float:
    """Convert value to float safely."""

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str | bytes | bytearray):
        try:
            return float(value)
        except ValueError:
            return default

    return default


def _safe_optional_float(value: object) -> float | None:
    """Convert value to optional float safely."""

    if value in (None, ""):
        return None

    return _safe_float(value)


def _safe_bool(value: object, *, default: bool = False) -> bool:
    """Convert common values to bool safely."""

    if isinstance(value, bool):
        return value

    if isinstance(value, int | float):
        return value != 0

    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"1", "true", "yes", "y", "on", "fired", "success"}:
            return True
        if normalised in {"0", "false", "no", "n", "off", "not_fired", "failed"}:
            return False

    return default


def _safe_str(value: object, *, default: str = "") -> str:
    """Convert value to stripped string."""

    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def _clamp_score(value: float) -> float:
    """Clamp score into 0..1."""

    return max(0.0, min(1.0, value))


def _normalise_state(value: object) -> SessionState:
    """Normalise raw state value."""

    if isinstance(value, SessionState):
        return value

    text = _safe_str(value, default=SessionState.HEALTHY.value)

    try:
        return parse_session_state(text)
    except ValueError:
        return SessionState.HEALTHY


def _normalise_signal_name(value: object) -> SignalName:
    """Normalise raw signal name value."""

    if isinstance(value, SignalName):
        return value

    text = _safe_str(value, default=SignalName.TOKEN_BURN.value)

    try:
        return parse_signal_name(text)
    except ValueError:
        return SignalName.TOKEN_BURN


def _format_timestamp(timestamp_ms: int | None) -> str:
    """Format a millisecond timestamp as compact UTC text."""

    if timestamp_ms is None:
        return "-"

    try:
        return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "-"


def _format_duration(start_ms: int | None, end_ms: int | None) -> str:
    """Format a simple duration."""

    if start_ms is None:
        return "-"

    effective_end_ms = end_ms
    if effective_end_ms is None:
        return "open"

    duration_ms = max(0, effective_end_ms - start_ms)
    total_seconds = duration_ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60

    if minutes >= 60:
        hours = minutes // 60
        remaining_minutes = minutes % 60
        return f"{hours}h {remaining_minutes}m"

    if minutes > 0:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def _shorten(text: str, *, max_chars: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    """Return bounded text."""

    if max_chars <= 0:
        return ""

    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean

    suffix = "... [truncated]"
    keep = max(0, max_chars - len(suffix))
    return f"{clean[:keep]}{suffix}"


def normalise_session_list_item(
    raw: SessionListItem | Mapping[str, Any] | object,
) -> SessionListItem:
    """Convert a raw record into a SessionListItem."""

    if isinstance(raw, SessionListItem):
        return raw

    session_id = _safe_str(
        _record_get(raw, "session_id", _record_get(raw, "id", "")),
        default="unknown-session",
    )

    state = _normalise_state(_record_get(raw, "state", SessionState.HEALTHY.value))

    return SessionListItem(
        session_id=session_id,
        state=state,
        health_score=_safe_optional_float(
            _record_get(raw, "health_score", _record_get(raw, "health", None))
        ),
        started_at_ms=_safe_optional_int(
            _record_get(raw, "started_at_ms", _record_get(raw, "started_at", None))
        ),
        ended_at_ms=_safe_optional_int(
            _record_get(raw, "ended_at_ms", _record_get(raw, "ended_at", None))
        ),
        updated_at_ms=_safe_optional_int(
            _record_get(raw, "updated_at_ms", _record_get(raw, "updated_at", None))
        ),
        tool_call_count=max(0, _safe_int(_record_get(raw, "tool_call_count", 0))),
        signal_count=max(0, _safe_int(_record_get(raw, "signal_count", 0))),
        total_tokens=max(0, _safe_int(_record_get(raw, "total_tokens", 0))),
        handoff_summary_path=_safe_str(
            _record_get(raw, "handoff_summary_path", None),
            default="",
        )
        or None,
    )


def normalise_session_signal_item(
    raw: SessionSignalItem | Mapping[str, Any] | object,
) -> SessionSignalItem:
    """Convert a raw record into a SessionSignalItem."""

    if isinstance(raw, SessionSignalItem):
        return raw

    return SessionSignalItem(
        signal_name=_normalise_signal_name(
            _record_get(raw, "signal_name", _record_get(raw, "name", "token_burn"))
        ),
        score=_clamp_score(_safe_float(_record_get(raw, "score", 0.0))),
        confidence=_clamp_score(_safe_float(_record_get(raw, "confidence", 1.0))),
        fired=_safe_bool(_record_get(raw, "fired", False)),
        explanation=_shorten(_safe_str(_record_get(raw, "explanation", ""))),
        timestamp_ms=_safe_optional_int(
            _record_get(raw, "timestamp_ms", _record_get(raw, "created_at", None))
        ),
    )


def normalise_session_tool_item(
    raw: SessionToolUseItem | Mapping[str, Any] | object,
) -> SessionToolUseItem:
    """Convert a raw record into a SessionToolUseItem."""

    if isinstance(raw, SessionToolUseItem):
        return raw

    error_text = _safe_str(
        _record_get(raw, "error_text", _record_get(raw, "error", "")),
    )

    success_raw = _record_get(raw, "success", None)
    success = _safe_bool(success_raw, default=True) if success_raw is not None else error_text == ""

    return SessionToolUseItem(
        tool_name=_safe_str(_record_get(raw, "tool_name", "unknown")),
        success=success,
        timestamp_ms=_safe_optional_int(
            _record_get(raw, "timestamp_ms", _record_get(raw, "created_at", None))
        ),
        total_tokens=max(0, _safe_int(_record_get(raw, "total_tokens", 0))),
        error_text=_shorten(error_text),
        input_hash=_safe_str(_record_get(raw, "input_hash", "")),
    )


def normalise_session_detail(
    session: SessionListItem | Mapping[str, Any] | object,
    *,
    signals: Sequence[SessionSignalItem | Mapping[str, Any] | object] = tuple(),
    tools: Sequence[SessionToolUseItem | Mapping[str, Any] | object] = tuple(),
    handoff_path: str | None = None,
    notes: Sequence[str] = tuple(),
) -> SessionDetail:
    """Build a normalised SessionDetail."""

    session_item = normalise_session_list_item(session)

    return SessionDetail(
        session=session_item,
        signals=tuple(normalise_session_signal_item(item) for item in signals),
        tools=tuple(normalise_session_tool_item(item) for item in tools),
        handoff_path=handoff_path or session_item.handoff_summary_path,
        notes=tuple(_shorten(note) for note in notes if note.strip()),
    )


def render_session_list(
    sessions: Sequence[SessionListItem | Mapping[str, Any] | object],
    *,
    limit: int = DEFAULT_SESSION_LIST_LIMIT,
) -> str:
    """Render a compact session list."""

    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1")

    items = tuple(normalise_session_list_item(item) for item in sessions)[:limit]

    if not items:
        return "Pilot sessions\n\nNo sessions found."

    lines = [
        "Pilot sessions",
        "",
        "session_id                 state            health  tools  signals  tokens   started           duration",
        "-" * 104,
    ]

    for item in items:
        lines.append(
            f"{_shorten(item.session_id, max_chars=24):24} "
            f"{item.state.value:16} "
            f"{item.display_health:>6} "
            f"{item.tool_call_count:>6} "
            f"{item.signal_count:>8} "
            f"{item.total_tokens:>7} "
            f"{_format_timestamp(item.started_at_ms):16} "
            f"{_format_duration(item.started_at_ms, item.ended_at_ms)}"
        )

    if len(sessions) > limit:
        lines.append("")
        lines.append(f"... showing {limit} of {len(sessions)} sessions")

    return "\n".join(lines)


def _render_signals(signals: Sequence[SessionSignalItem]) -> list[str]:
    """Render detail signal rows."""

    if not signals:
        return ["## Signals", "", "No signal records found."]

    lines = [
        "## Signals",
        "",
        "signal                  score  conf  fired  time              explanation",
        "-" * 86,
    ]

    sorted_signals = sorted(
        signals,
        key=lambda item: (item.fired, item.score, item.timestamp_ms or 0),
        reverse=True,
    )

    for signal in sorted_signals[:DEFAULT_MAX_DETAIL_ITEMS]:
        lines.append(
            f"{signal.signal_name.value:22} "
            f"{signal.score:>5.2f} "
            f"{signal.confidence:>5.2f} "
            f"{signal.fired!s:5} "
            f"{_format_timestamp(signal.timestamp_ms):16} "
            f"{signal.explanation}"
        )

    return lines


def _render_tools(tools: Sequence[SessionToolUseItem]) -> list[str]:
    """Render detail tool rows."""

    if not tools:
        return ["## Tool Calls", "", "No tool-use records found."]

    lines = [
        "## Tool Calls",
        "",
        "tool                 ok     tokens  time              error",
        "-" * 76,
    ]

    for tool in tools[:DEFAULT_MAX_DETAIL_ITEMS]:
        lines.append(
            f"{tool.tool_name:20} "
            f"{tool.success!s:5} "
            f"{tool.total_tokens:>6} "
            f"{_format_timestamp(tool.timestamp_ms):16} "
            f"{tool.error_text}"
        )

    if len(tools) > DEFAULT_MAX_DETAIL_ITEMS:
        lines.append(f"... showing {DEFAULT_MAX_DETAIL_ITEMS} of {len(tools)} tool calls")

    return lines


def render_session_detail(detail: SessionDetail) -> str:
    """Render one session detail view."""

    session = detail.session

    lines = [
        f"Pilot session: {session.session_id}",
        "",
        "## Summary",
        "",
        f"State: {session.state.value}",
        f"Health: {session.display_health}",
        f"Started: {_format_timestamp(session.started_at_ms)}",
        f"Ended: {_format_timestamp(session.ended_at_ms)}",
        f"Duration: {_format_duration(session.started_at_ms, session.ended_at_ms)}",
        f"Tool calls: {session.tool_call_count}",
        f"Signals: {session.signal_count}",
        f"Total tokens: {session.total_tokens}",
    ]

    if detail.handoff_path:
        lines.append(f"Handoff: {detail.handoff_path}")

    lines.extend(["", *_render_signals(detail.signals)])
    lines.extend(["", *_render_tools(detail.tools)])

    if detail.notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in detail.notes)

    return "\n".join(lines)


def session_list_summary(
    sessions: Sequence[SessionListItem | Mapping[str, Any] | object],
) -> dict[str, object]:
    """Return a serialisable summary for a session list."""

    items = tuple(normalise_session_list_item(item) for item in sessions)
    state_counts: dict[str, int] = {}

    for item in items:
        state_counts[item.state.value] = state_counts.get(item.state.value, 0) + 1

    return {
        "session_count": len(items),
        "open_count": sum(1 for item in items if item.is_open),
        "state_counts": state_counts,
        "total_tool_calls": sum(item.tool_call_count for item in items),
        "total_tokens": sum(item.total_tokens for item in items),
    }


def session_detail_summary(detail: SessionDetail) -> dict[str, object]:
    """Return a serialisable summary for one session detail."""

    return {
        "session_id": detail.session.session_id,
        "state": detail.session.state.value,
        "health_score": detail.session.health_score,
        "tool_call_count": len(detail.tools),
        "signal_count": len(detail.signals),
        "fired_signal_count": sum(1 for item in detail.signals if item.fired),
        "has_handoff": detail.handoff_path is not None,
    }
