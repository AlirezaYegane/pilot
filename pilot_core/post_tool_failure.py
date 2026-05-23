"""PostToolUseFailure hook implementation.

This module records failed tool calls in Pilot's local SQLite database.

Design goals:
- fail silently when used from a hook
- accept slightly different Claude Code payload shapes
- record enough data for future error-cascade signal detection
- avoid heavy signal evaluation in Day 20
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from pilot_core.constants import SessionState
from pilot_core.paths import ensure_runtime_dirs
from pilot_core.safety import log_exception

JsonMap = Mapping[str, Any]


@dataclass(frozen=True)
class ToolFailureRecord:
    """Normalized representation of a failed tool call."""

    session_id: str
    tool_name: str
    tool_input: dict[str, Any]
    error_type: str
    error_message: str
    timestamp_ms: int
    duration_ms: int | None
    turn_index: int
    input_hash: str
    input_size: int
    output_size: int
    error_payload_json: str
    tool_input_json: str


def now_ms() -> int:
    """Return current Unix time in milliseconds."""

    return int(time.time() * 1000)


def _json_dumps(value: object) -> str:
    """Return stable JSON text for hashing/storage."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _as_mapping(value: object) -> dict[str, Any]:
    """Return a plain dict if value is mapping-like, otherwise an empty dict."""

    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_str(value: object, *, default: str = "") -> str:
    """Coerce a value into a string with a fallback."""

    if value is None:
        return default
    text = str(value)
    return text if text else default


def _as_optional_int(value: object) -> int | None:
    """Coerce value to int when possible."""

    if value is None:
        return None

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value)

    if isinstance(value, str | bytes | bytearray):
        try:
            return int(value)
        except ValueError:
            return None

    return None


def _as_int(value: object, *, default: int) -> int:
    """Coerce value to int with a fallback."""

    parsed = _as_optional_int(value)
    return default if parsed is None else parsed


def _nested_value(payload: JsonMap, section_name: str, key: str) -> object | None:
    """Read payload[section_name][key] if section is mapping-like."""

    section = payload.get(section_name)
    if isinstance(section, Mapping):
        value: object | None = section.get(key)
        return value
    return None


def _first_present(payload: JsonMap, keys: tuple[str, ...]) -> object | None:
    """Return first present top-level value from payload."""

    for key in keys:
        value: object | None = payload.get(key)
        if value is not None:
            return value
    return None


def stable_input_hash(tool_name: str, tool_input: Mapping[str, Any]) -> str:
    """Hash tool name and input so repeated failing calls can be detected later."""

    normalized = {
        "tool_name": tool_name,
        "tool_input": dict(tool_input),
    }
    raw = _json_dumps(normalized).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalize_failure_payload(payload: JsonMap) -> ToolFailureRecord:
    """Normalize a Claude Code PostToolUseFailure payload.

    The exact payload shape can vary across hook versions, so this accepts
    several common aliases.
    """

    session_id = _as_str(
        _first_present(payload, ("session_id", "sessionId"))
        or _nested_value(payload, "session", "id"),
        default="unknown-session",
    )

    tool_name = _as_str(
        _first_present(payload, ("tool_name", "toolName", "name"))
        or _nested_value(payload, "tool", "name"),
        default="unknown_tool",
    )

    tool_input = _as_mapping(
        _first_present(payload, ("tool_input", "toolInput", "input", "parameters"))
        or _nested_value(payload, "tool", "input")
    )

    error_payload = _as_mapping(
        _first_present(payload, ("error", "tool_error", "toolError", "failure"))
    )

    error_type = _as_str(
        _first_present(payload, ("error_type", "errorType"))
        or error_payload.get("type")
        or error_payload.get("name"),
        default="ToolFailure",
    )

    error_message = _as_str(
        _first_present(payload, ("error_message", "errorMessage", "message"))
        or error_payload.get("message")
        or error_payload.get("detail"),
        default="",
    )

    timestamp_ms = _as_int(
        _first_present(payload, ("timestamp_ms", "timestampMs", "timestamp")),
        default=now_ms(),
    )

    duration_ms = _as_optional_int(_first_present(payload, ("duration_ms", "durationMs")))

    turn_index = _as_int(
        _first_present(payload, ("turn_index", "turnIndex"))
        or _nested_value(payload, "turn", "index"),
        default=0,
    )

    tool_input_json = _json_dumps(tool_input)
    error_payload_json = _json_dumps(
        {
            "error_type": error_type,
            "error_message": error_message,
            "raw_error": error_payload,
        }
    )

    return ToolFailureRecord(
        session_id=session_id,
        tool_name=tool_name,
        tool_input=tool_input,
        error_type=error_type,
        error_message=error_message,
        timestamp_ms=timestamp_ms,
        duration_ms=duration_ms,
        turn_index=turn_index,
        input_hash=stable_input_hash(tool_name, tool_input),
        input_size=len(tool_input_json.encode("utf-8")),
        output_size=len(error_payload_json.encode("utf-8")),
        error_payload_json=error_payload_json,
        tool_input_json=tool_input_json,
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open SQLite connection with Pilot runtime pragmas."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys=ON;")
    connection.execute("PRAGMA busy_timeout=5000;")
    connection.execute("PRAGMA journal_mode=WAL;")
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    """Return column names for an existing table."""

    rows = connection.execute(f"PRAGMA table_info({table_name});").fetchall()
    return {str(row[1]) for row in rows}


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    """Return True if table exists."""

    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?;",
        (table_name,),
    ).fetchone()
    return row is not None


def _insert_existing_columns(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    values: Mapping[str, object],
    prefix: str = "INSERT",
) -> None:
    """Insert only columns that exist in the current schema.

    This keeps the hook tolerant while the schema evolves during the build.
    """

    if not _table_exists(connection, table_name):
        return

    existing_columns = _table_columns(connection, table_name)
    selected_items = [(key, value) for key, value in values.items() if key in existing_columns]

    if not selected_items:
        return

    columns = [key for key, _value in selected_items]
    parameters = [value for _key, value in selected_items]

    column_sql = ", ".join(columns)
    placeholder_sql = ", ".join("?" for _column in columns)
    sql = f"{prefix} INTO {table_name} ({column_sql}) VALUES ({placeholder_sql});"
    connection.execute(sql, parameters)


def _ensure_session_row(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    timestamp_ms: int,
) -> None:
    """Create a minimal session row if the schema supports it."""

    values: dict[str, object] = {
        "id": session_id,
        "started_at": timestamp_ms,
        "state": SessionState.HEALTHY.value,
    }
    _insert_existing_columns(
        connection,
        table_name="sessions",
        values=values,
        prefix="INSERT OR IGNORE",
    )


def _increment_active_turn(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    turn_index: int,
) -> None:
    """Increment per-turn tool/error counters when turns table exists."""

    if not _table_exists(connection, "turns"):
        return

    columns = _table_columns(connection, "turns")
    assignments: list[str] = []

    if "tool_count" in columns:
        assignments.append("tool_count = COALESCE(tool_count, 0) + 1")
    if "error_count" in columns:
        assignments.append("error_count = COALESCE(error_count, 0) + 1")

    if not assignments:
        return

    assignment_sql = ", ".join(assignments)

    row = connection.execute(
        """
        SELECT turn_index
        FROM turns
        WHERE session_id = ?
        ORDER BY turn_index DESC
        LIMIT 1;
        """,
        (session_id,),
    ).fetchone()

    effective_turn_index = turn_index
    if row is not None:
        effective_turn_index = int(row[0])

    connection.execute(
        f"""
        UPDATE turns
        SET {assignment_sql}
        WHERE session_id = ? AND turn_index = ?;
        """,
        (session_id, effective_turn_index),
    )


def record_tool_failure(
    record: ToolFailureRecord,
    *,
    db_path: Path | None = None,
) -> None:
    """Persist a failed tool call to SQLite."""

    runtime_paths = ensure_runtime_dirs()
    effective_db_path = db_path or runtime_paths.db_path

    with _connect(effective_db_path) as connection:
        _ensure_session_row(
            connection,
            session_id=record.session_id,
            timestamp_ms=record.timestamp_ms,
        )

        tool_use_values: dict[str, object] = {
            "session_id": record.session_id,
            "turn_index": record.turn_index,
            "timestamp_ms": record.timestamp_ms,
            "tool_name": record.tool_name,
            "input_hash": record.input_hash,
            "input_size": record.input_size,
            "output_size": record.output_size,
            "success": 0,
            "duration_ms": record.duration_ms,
            "input_tokens_est": 0,
            "output_tokens_est": 0,
            "tool_input_json": record.tool_input_json,
            "input_payload_json": record.tool_input_json,
            "error_type": record.error_type,
            "error_message": record.error_message,
            "error_payload_json": record.error_payload_json,
            "output_payload_json": record.error_payload_json,
            "created_at": record.timestamp_ms,
            "updated_at": record.timestamp_ms,
        }

        _insert_existing_columns(
            connection,
            table_name="tool_uses",
            values=tool_use_values,
        )

        _increment_active_turn(
            connection,
            session_id=record.session_id,
            turn_index=record.turn_index,
        )

        connection.commit()


def handle_payload(payload: JsonMap, *, db_path: Path | None = None) -> None:
    """Normalize and persist a failure payload."""

    record = normalize_failure_payload(payload)
    record_tool_failure(record, db_path=db_path)


def main(stdin: TextIO | None = None) -> int:
    """CLI/hook entrypoint.

    Always returns 0 because hook failures must never block the user.
    """

    stream = stdin or sys.stdin

    try:
        payload = json.load(stream)
        if not isinstance(payload, Mapping):
            raise TypeError("PostToolUseFailure payload must be a JSON object")

        handle_payload(payload)
    except Exception as exc:
        log_exception(
            exc,
            context="post_tool_failure",
            include_traceback=True,
        )

    return 0


__all__ = [
    "ToolFailureRecord",
    "handle_payload",
    "main",
    "normalize_failure_payload",
    "record_tool_failure",
    "stable_input_hash",
]


if __name__ == "__main__":
    raise SystemExit(main())
