"""Handoff summary extractor.

Day 44 turns stored session records into the Day 43 HandoffSchema.

Scope for Day 44:
- read flexible rows from SQLite or in-memory records
- collect key turns
- collect signal history
- infer task/progress/files/decisions/next step

Out of scope:
- blocker extraction from failing loops
- do-not-redo extraction from repeated attempts
- markdown rendering
- stop-hook integration
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pilot_core.handoff import (
    HandoffDecision,
    HandoffFileChange,
    HandoffFileStatus,
    HandoffSchema,
)

DEFAULT_MAX_KEY_TURNS = 8
DEFAULT_MAX_SIGNAL_HISTORY = 12
DEFAULT_MAX_FILES_MODIFIED = 20
DEFAULT_MAX_DECISIONS = 6
DEFAULT_TEXT_PREVIEW_CHARS = 220

TURN_TABLE_CANDIDATES = (
    "session_turns",
    "turns",
    "events",
    "session_events",
    "tool_calls",
    "tool_uses",
)

SIGNAL_TABLE_CANDIDATES = (
    "signal_results",
    "session_signals",
    "signals",
    "signal_history",
)


@dataclass(frozen=True)
class ExtractedTurn:
    """A compact turn/tool record used for handoff extraction."""

    turn_index: int | None
    role: str
    content: str
    summary: str
    tool_name: str | None = None
    file_path: str | None = None
    success: bool | None = None
    timestamp_ms: int | None = None

    @property
    def display_text(self) -> str:
        """Return the best human-readable text for this turn."""

        if self.summary.strip():
            return self.summary.strip()

        return self.content.strip()


@dataclass(frozen=True)
class ExtractedSignal:
    """A compact signal result used for handoff extraction."""

    signal_name: str
    score: float
    fired: bool
    severity: str | None = None
    turn_index: int | None = None
    timestamp_ms: int | None = None


@dataclass(frozen=True)
class HandoffExtractionResult:
    """Complete result returned by Day 44 extraction."""

    handoff: HandoffSchema
    key_turns: tuple[ExtractedTurn, ...]
    signal_history: tuple[ExtractedSignal, ...]
    source: str

    @property
    def is_valid(self) -> bool:
        """Return True when the generated handoff schema is valid."""

        return self.handoff.is_valid()


def _record_get(raw: object, key: str, default: object = None) -> object:
    """Read a key from mapping-like or object-like records."""

    if isinstance(raw, Mapping):
        return raw.get(key, default)

    return getattr(raw, key, default)


def _safe_int(value: object, *, default: int | None = None) -> int | None:
    """Convert value to int without crashing on bad payloads."""

    if value is None:
        return default

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int | float):
        return int(value)

    if isinstance(value, str | bytes | bytearray):
        text = value.decode() if isinstance(value, bytes | bytearray) else value
        if not text.strip():
            return default
        try:
            return int(float(text))
        except ValueError:
            return default

    return default


def _safe_float(value: object, *, default: float = 0.0) -> float:
    """Convert value to float without crashing on bad payloads."""

    if value is None:
        return default

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str | bytes | bytearray):
        text = value.decode() if isinstance(value, bytes | bytearray) else value
        if not text.strip():
            return default
        try:
            return float(text)
        except ValueError:
            return default

    return default


def _safe_bool(value: object, *, default: bool | None = None) -> bool | None:
    """Convert value to bool without crashing on bad payloads."""

    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, int | float):
        return bool(value)

    if isinstance(value, str | bytes | bytearray):
        text = value.decode() if isinstance(value, bytes | bytearray) else value
        normalised = text.strip().lower()

        if normalised in {"1", "true", "yes", "y", "on", "success", "passed"}:
            return True

        if normalised in {"0", "false", "no", "n", "off", "failure", "failed"}:
            return False

    return default


def _clean_text(value: object, *, max_chars: int = DEFAULT_TEXT_PREVIEW_CHARS) -> str:
    """Return compact single-line text."""

    if value is None:
        return ""

    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = " ".join(part.strip() for part in text.splitlines() if part.strip())

    if len(text) <= max_chars:
        return text

    return f"{text[: max(0, max_chars - 15)]}... [truncated]"


def _normalise_path(value: object) -> str | None:
    """Return a stable file path or None."""

    if value in (None, ""):
        return None

    path = str(value).strip().replace("\\", "/")

    while "//" in path:
        path = path.replace("//", "/")

    return path or None


def _nested_mapping(raw: object, key: str) -> Mapping[str, object] | None:
    """Read a nested mapping value when available."""

    value = _record_get(raw, key, None)

    if isinstance(value, Mapping):
        return value

    return None


def _extract_file_path(raw: object) -> str | None:
    """Extract a file path from common DB/hook payload shapes."""

    for key in ("file_path", "path", "filepath", "target_file"):
        path = _normalise_path(_record_get(raw, key, None))
        if path is not None:
            return path

    for nested_key in ("tool_input", "input_payload", "input", "payload"):
        nested = _nested_mapping(raw, nested_key)
        if nested is None:
            continue

        for key in ("file_path", "path", "filepath", "target_file"):
            path = _normalise_path(nested.get(key))
            if path is not None:
                return path

    return None


def normalise_turn(raw: Mapping[str, object] | object) -> ExtractedTurn:
    """Normalise a DB/event row into an ExtractedTurn."""

    tool_name_value = _record_get(raw, "tool_name", _record_get(raw, "tool", None))
    tool_name = str(tool_name_value) if tool_name_value not in (None, "") else None

    role_value = _record_get(raw, "role", None)
    if role_value not in (None, ""):
        role = str(role_value)
    elif tool_name is not None:
        role = "tool"
    else:
        role = "unknown"

    content = _clean_text(
        _record_get(
            raw,
            "content",
            _record_get(
                raw,
                "text",
                _record_get(
                    raw,
                    "message",
                    _record_get(raw, "response", _record_get(raw, "prompt", "")),
                ),
            ),
        )
    )

    summary = _clean_text(_record_get(raw, "summary", _record_get(raw, "turn_summary", "")))

    success_value = _record_get(raw, "success", None)
    success: bool | None
    if success_value is None and _record_get(raw, "error", None) not in (None, "", {}, []):
        success = False
    else:
        success = _safe_bool(success_value, default=None)

    return ExtractedTurn(
        turn_index=_safe_int(_record_get(raw, "turn_index", _record_get(raw, "turn", None))),
        role=role,
        content=content,
        summary=summary,
        tool_name=tool_name,
        file_path=_extract_file_path(raw),
        success=success,
        timestamp_ms=_safe_int(_record_get(raw, "timestamp_ms", None)),
    )


def normalise_signal(raw: Mapping[str, object] | object) -> ExtractedSignal:
    """Normalise a DB/event row into an ExtractedSignal."""

    signal_name = _clean_text(
        _record_get(raw, "signal_name", _record_get(raw, "name", _record_get(raw, "signal", ""))),
        max_chars=80,
    )
    score = _safe_float(_record_get(raw, "score", _record_get(raw, "badness", 0.0)))
    fired = _safe_bool(_record_get(raw, "fired", None), default=None)
    if fired is None:
        fired = score >= 0.60

    severity_value = _record_get(raw, "severity", None)
    severity = str(severity_value) if severity_value not in (None, "") else None

    return ExtractedSignal(
        signal_name=signal_name or "unknown",
        score=max(0.0, min(1.0, score)),
        fired=fired,
        severity=severity,
        turn_index=_safe_int(_record_get(raw, "turn_index", _record_get(raw, "turn", None))),
        timestamp_ms=_safe_int(_record_get(raw, "timestamp_ms", None)),
    )


def _turn_sort_key(turn: ExtractedTurn) -> tuple[int, int]:
    """Return stable chronological sort key for turns."""

    turn_index = turn.turn_index if turn.turn_index is not None else 1_000_000_000
    timestamp = turn.timestamp_ms if turn.timestamp_ms is not None else 1_000_000_000
    return (turn_index, timestamp)


def _signal_sort_key(signal: ExtractedSignal) -> tuple[int, int]:
    """Return stable chronological sort key for signals."""

    turn_index = signal.turn_index if signal.turn_index is not None else 1_000_000_000
    timestamp = signal.timestamp_ms if signal.timestamp_ms is not None else 1_000_000_000
    return (turn_index, timestamp)


def _is_key_turn(turn: ExtractedTurn) -> bool:
    """Return True when a turn is useful enough for handoff context."""

    if turn.role.lower() == "user":
        return True

    if turn.success is False:
        return True

    if turn.summary.strip():
        return True

    if turn.file_path is not None:
        return True

    if turn.tool_name in {"Edit", "MultiEdit", "Write", "Bash"}:
        return True

    return bool(turn.content.strip())


def collect_key_turns(
    rows: Sequence[Mapping[str, object] | object],
    *,
    max_turns: int = DEFAULT_MAX_KEY_TURNS,
) -> tuple[ExtractedTurn, ...]:
    """Collect the most useful turns for a handoff."""

    if max_turns <= 0:
        return tuple()

    turns = tuple(sorted((normalise_turn(row) for row in rows), key=_turn_sort_key))
    candidates = tuple(turn for turn in turns if _is_key_turn(turn))

    if not candidates:
        return turns[-max_turns:]

    return candidates[-max_turns:]


def collect_signal_history(
    rows: Sequence[Mapping[str, object] | object],
    *,
    max_signals: int = DEFAULT_MAX_SIGNAL_HISTORY,
) -> tuple[ExtractedSignal, ...]:
    """Collect important signal history for a handoff."""

    if max_signals <= 0:
        return tuple()

    signals = tuple(sorted((normalise_signal(row) for row in rows), key=_signal_sort_key))
    candidates = tuple(signal for signal in signals if signal.fired or signal.score > 0.0)

    if not candidates:
        return tuple()

    return candidates[-max_signals:]


def _infer_task(turns: Sequence[ExtractedTurn]) -> str:
    """Infer the session task from the earliest user turn."""

    for turn in turns:
        if turn.role.lower() == "user" and turn.display_text:
            return _clean_text(turn.display_text, max_chars=180)

    for turn in turns:
        if turn.display_text:
            return _clean_text(turn.display_text, max_chars=180)

    return "Continue Pilot session"


def _infer_progress(turns: Sequence[ExtractedTurn], signals: Sequence[ExtractedSignal]) -> str:
    """Infer progress text from key turns and signal history."""

    useful_turns = [turn for turn in turns if turn.display_text]

    if useful_turns:
        snippets = [_clean_text(turn.display_text, max_chars=140) for turn in useful_turns[-4:]]
        progress = " | ".join(snippets)
    else:
        progress = "No detailed turn summary was available in storage."

    fired_count = sum(1 for signal in signals if signal.fired)
    if signals:
        progress = (
            f"{progress} Signal history collected: {len(signals)} events, {fired_count} fired."
        )

    return progress


def _infer_next_step(turns: Sequence[ExtractedTurn]) -> str:
    """Infer a next step without doing Day 45 blocker analysis."""

    for turn in reversed(turns):
        text = turn.display_text.lower()
        if "next step" in text or "next:" in text or "گام بعد" in text:
            return _clean_text(turn.display_text, max_chars=180)

    if turns:
        return "Continue from the latest extracted key turn and verify the current quality gate."

    return "Review the previous session state and continue with the next implementation step."


def _status_from_tool(tool_name: str | None) -> HandoffFileStatus:
    """Infer a file status from a tool name."""

    if tool_name == "Write":
        return HandoffFileStatus.CREATED

    if tool_name in {"Edit", "MultiEdit"}:
        return HandoffFileStatus.MODIFIED

    return HandoffFileStatus.UNKNOWN


def _extract_files(turns: Sequence[ExtractedTurn]) -> tuple[HandoffFileChange, ...]:
    """Extract changed/mentioned files from key turns."""

    files: dict[str, HandoffFileChange] = {}

    for turn in turns:
        if turn.file_path is None:
            continue

        if turn.file_path in files:
            continue

        files[turn.file_path] = HandoffFileChange(
            path=turn.file_path,
            status=_status_from_tool(turn.tool_name),
            reason=f"Observed in {turn.tool_name or turn.role} record",
            important=True,
        )

        if len(files) >= DEFAULT_MAX_FILES_MODIFIED:
            break

    return tuple(files.values())


def _extract_decisions(turns: Sequence[ExtractedTurn]) -> tuple[HandoffDecision, ...]:
    """Extract lightweight decision hints from turn summaries.

    This is intentionally conservative. Day 45 handles deeper blocker and
    failed-attempt extraction.
    """

    decisions: list[HandoffDecision] = []

    for turn in turns:
        text = turn.display_text
        lowered = text.lower()

        if "decision:" not in lowered and "decided" not in lowered:
            continue

        decisions.append(
            HandoffDecision(
                title=_clean_text(text, max_chars=160),
                rationale="Extracted from a key turn summary.",
            )
        )

        if len(decisions) >= DEFAULT_MAX_DECISIONS:
            break

    return tuple(decisions)


def _signal_notes(signals: Sequence[ExtractedSignal]) -> tuple[str, ...]:
    """Render signal history as schema notes."""

    if not signals:
        return ("No signal history was available in storage.",)

    top = sorted(signals, key=lambda signal: (signal.fired, signal.score), reverse=True)[:5]
    fragments = [
        f"{signal.signal_name}: score={signal.score:.2f}, fired={signal.fired}" for signal in top
    ]

    return (f"Signal history: {'; '.join(fragments)}",)


def extract_handoff_from_records(
    *,
    session_id: str | None,
    turn_rows: Sequence[Mapping[str, object] | object],
    signal_rows: Sequence[Mapping[str, object] | object] = tuple(),
    max_key_turns: int = DEFAULT_MAX_KEY_TURNS,
    max_signal_history: int = DEFAULT_MAX_SIGNAL_HISTORY,
    source: str = "records",
) -> HandoffExtractionResult:
    """Extract a HandoffSchema from already-loaded records."""

    all_turns = tuple(sorted((normalise_turn(row) for row in turn_rows), key=_turn_sort_key))
    key_turns = collect_key_turns(turn_rows, max_turns=max_key_turns)
    signal_history = collect_signal_history(signal_rows, max_signals=max_signal_history)

    turns_for_inference = key_turns if key_turns else all_turns

    handoff = HandoffSchema(
        session_id=session_id,
        task=_infer_task(turns_for_inference),
        progress=_infer_progress(turns_for_inference, signal_history),
        decisions=_extract_decisions(turns_for_inference),
        files_modified=_extract_files(turns_for_inference),
        blockers=tuple(),
        next_step=_infer_next_step(turns_for_inference),
        do_not_redo=tuple(),
        notes=_signal_notes(signal_history),
    )

    return HandoffExtractionResult(
        handoff=handoff,
        key_turns=key_turns,
        signal_history=signal_history,
        source=source,
    )


def _quote_identifier(identifier: str) -> str:
    """Quote a SQLite identifier after a strict safety check."""

    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"Unsafe SQLite identifier: {identifier!r}")

    return f'"{identifier}"'


def _table_names(connection: sqlite3.Connection) -> set[str]:
    """Return user table names in a SQLite database."""

    cursor = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )

    return {str(row[0]) for row in cursor.fetchall()}


def _columns_for_table(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    """Return column names for a SQLite table."""

    cursor = connection.execute(f"PRAGMA table_info({_quote_identifier(table_name)})")
    return tuple(str(row[1]) for row in cursor.fetchall())


def _order_clause(columns: Sequence[str]) -> str:
    """Return a safe ORDER BY clause for known chronological columns."""

    order_columns = [
        column for column in ("turn_index", "timestamp_ms", "created_at", "id") if column in columns
    ]

    if not order_columns:
        return ""

    quoted = ", ".join(_quote_identifier(column) for column in order_columns)
    return f" ORDER BY {quoted}"


def _select_rows(
    connection: sqlite3.Connection,
    table_name: str,
    *,
    session_id: str | None,
    limit: int,
) -> list[dict[str, object]]:
    """Select rows from a SQLite table using flexible schema conventions."""

    columns = _columns_for_table(connection, table_name)
    quoted_table = _quote_identifier(table_name)

    where_clause = ""
    params: list[object] = []

    if session_id is not None and "session_id" in columns:
        where_clause = " WHERE session_id = ?"
        params.append(session_id)

    query = f"SELECT * FROM {quoted_table}{where_clause}{_order_clause(columns)} LIMIT ?"
    params.append(limit)

    cursor = connection.execute(query, params)
    cursor_columns = [description[0] for description in cursor.description or []]

    rows: list[dict[str, object]] = []
    for row in cursor.fetchall():
        rows.append(dict(zip(cursor_columns, row, strict=False)))

    return rows


def _read_candidate_rows(
    connection: sqlite3.Connection,
    *,
    candidates: Sequence[str],
    session_id: str | None,
    limit: int,
) -> list[dict[str, object]]:
    """Read rows from the first matching candidate tables."""

    available = _table_names(connection)
    rows: list[dict[str, object]] = []

    for table_name in candidates:
        if table_name not in available:
            continue

        rows.extend(
            _select_rows(
                connection,
                table_name,
                session_id=session_id,
                limit=limit,
            )
        )

    return rows


def extract_handoff_from_db(
    connection: sqlite3.Connection,
    *,
    session_id: str | None,
    max_key_turns: int = DEFAULT_MAX_KEY_TURNS,
    max_signal_history: int = DEFAULT_MAX_SIGNAL_HISTORY,
) -> HandoffExtractionResult:
    """Extract a handoff summary from a SQLite connection.

    The extractor is intentionally schema-flexible. It supports several likely
    table names so it can work during early storage iterations without forcing a
    storage migration.
    """

    turn_rows = _read_candidate_rows(
        connection,
        candidates=TURN_TABLE_CANDIDATES,
        session_id=session_id,
        limit=500,
    )
    signal_rows = _read_candidate_rows(
        connection,
        candidates=SIGNAL_TABLE_CANDIDATES,
        session_id=session_id,
        limit=500,
    )

    return extract_handoff_from_records(
        session_id=session_id,
        turn_rows=turn_rows,
        signal_rows=signal_rows,
        max_key_turns=max_key_turns,
        max_signal_history=max_signal_history,
        source="sqlite",
    )


def handoff_extraction_summary(result: HandoffExtractionResult) -> dict[str, object]:
    """Return a compact JSON-safe summary for smoke scripts and tests."""

    return {
        "source": result.source,
        "session_id": result.handoff.session_id,
        "task": result.handoff.task,
        "progress": result.handoff.progress,
        "next_step": result.handoff.next_step,
        "key_turn_count": len(result.key_turns),
        "signal_history_count": len(result.signal_history),
        "file_count": len(result.handoff.files_modified),
        "decision_count": len(result.handoff.decisions),
        "is_valid": result.is_valid,
        "validation_errors": list(result.handoff.validation_errors()),
    }
