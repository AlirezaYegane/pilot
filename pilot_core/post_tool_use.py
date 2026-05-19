"""PostToolUse capture logic.

This module records successful tool calls after they complete.

Day 19 scope:
- parse PostToolUse payloads
- estimate input/output tokens
- record one successful tool_uses row
- increment current turn tool_count when possible
- update session token totals when possible

Signal detection is intentionally not implemented here yet. That starts in the
Signal Engine milestone.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pilot_core.constants import SessionState
from pilot_core.paths import ensure_runtime_dirs, resolve_runtime_paths
from pilot_core.safety import log_exception
from pilot_core.token_estimation import (
    estimate_token_count,
    payload_size_bytes,
    stable_json_dumps,
)

SQLiteValue = str | int | float | bytes | None


@dataclass(frozen=True)
class PostToolUseCapture:
    """Result of recording a successful PostToolUse payload."""

    session_id: str
    tool_name: str
    turn_index: int | None
    timestamp_ms: int
    input_hash: str
    input_tokens_est: int
    output_tokens_est: int
    recorded: bool
    reason: str | None = None


def current_time_ms() -> int:
    """Return current Unix time in milliseconds."""

    return int(time.time() * 1000)


def _as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _as_str(value: object, *, default: str = "") -> str:
    if isinstance(value, str) and value:
        return value
    return default


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _quote_identifier(name: str) -> str:
    if not name.replace("_", "").isalnum():
        msg = f"Unsafe SQLite identifier: {name!r}"
        raise ValueError(msg)
    return f'"{name}"'


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?;",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()

    quoted = _quote_identifier(table_name)
    rows = conn.execute(f"PRAGMA table_info({quoted});").fetchall()
    return {str(row[1]) for row in rows}


def _insert_adaptive(
    conn: sqlite3.Connection,
    table_name: str,
    values: Mapping[str, SQLiteValue],
) -> bool:
    columns = _table_columns(conn, table_name)
    selected_keys = [key for key in values if key in columns]

    if not selected_keys:
        return False

    quoted_table = _quote_identifier(table_name)
    quoted_columns = ", ".join(_quote_identifier(key) for key in selected_keys)
    placeholders = ", ".join("?" for _ in selected_keys)
    params = tuple(values[key] for key in selected_keys)

    conn.execute(
        f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders});",
        params,
    )
    return True


def _tool_input_from_payload(payload: Mapping[str, object]) -> object:
    if "tool_input" in payload:
        return payload["tool_input"]
    if "input" in payload:
        return payload["input"]
    return {}


def _tool_response_from_payload(payload: Mapping[str, object]) -> object:
    if "tool_response" in payload:
        return payload["tool_response"]
    if "tool_result" in payload:
        return payload["tool_result"]
    if "response" in payload:
        return payload["response"]
    if "output" in payload:
        return payload["output"]
    return {}


def _input_hash(tool_name: str, tool_input: object) -> str:
    digest_input = f"{tool_name}\0{stable_json_dumps(tool_input)}"
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def _ensure_session_exists(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    timestamp_ms: int,
) -> None:
    if not _table_exists(conn, "sessions"):
        return

    columns = _table_columns(conn, "sessions")
    if "id" not in columns:
        return

    row = conn.execute(
        'SELECT 1 FROM "sessions" WHERE id = ? LIMIT 1;',
        (session_id,),
    ).fetchone()

    if row is not None:
        return

    values: dict[str, SQLiteValue] = {
        "id": session_id,
        "started_at": timestamp_ms,
        "state": SessionState.HEALTHY.value,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "estimated_cost_usd": 0.0,
    }

    _insert_adaptive(conn, "sessions", values)


def _latest_turn_index(conn: sqlite3.Connection, session_id: str) -> int | None:
    columns = _table_columns(conn, "turns")
    if not {"session_id", "turn_index"}.issubset(columns):
        return None

    row = conn.execute(
        'SELECT MAX(turn_index) FROM "turns" WHERE session_id = ?;',
        (session_id,),
    ).fetchone()

    if row is None or row[0] is None:
        return None

    return int(row[0])


def _update_turn_tool_count(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_index: int | None,
) -> None:
    if turn_index is None:
        return

    columns = _table_columns(conn, "turns")
    if not {"session_id", "turn_index", "tool_count"}.issubset(columns):
        return

    conn.execute(
        """
        UPDATE turns
        SET tool_count = COALESCE(tool_count, 0) + 1
        WHERE session_id = ? AND turn_index = ?;
        """,
        (session_id, turn_index),
    )


def _update_session_token_totals(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    input_tokens_est: int,
    output_tokens_est: int,
) -> None:
    columns = _table_columns(conn, "sessions")
    if "id" not in columns:
        return

    set_parts: list[str] = []
    params: list[int | str] = []

    if "total_input_tokens" in columns:
        set_parts.append("total_input_tokens = COALESCE(total_input_tokens, 0) + ?")
        params.append(input_tokens_est)

    if "total_output_tokens" in columns:
        set_parts.append("total_output_tokens = COALESCE(total_output_tokens, 0) + ?")
        params.append(output_tokens_est)

    if not set_parts:
        return

    params.append(session_id)

    conn.execute(
        f'UPDATE "sessions" SET {", ".join(set_parts)} WHERE id = ?;',
        tuple(params),
    )


def record_post_tool_use(
    payload: Mapping[str, object],
    *,
    db_path: str | Path | None = None,
) -> PostToolUseCapture:
    """Record a successful PostToolUse event.

    This function is deliberately tolerant of partial schemas. It inserts only
    columns that exist in the local SQLite database, which keeps older dev
    databases from breaking the hook.
    """

    session_id = _as_str(payload.get("session_id"))
    tool_name = _as_str(payload.get("tool_name"), default="unknown")
    timestamp_ms = _as_int(payload.get("timestamp_ms")) or current_time_ms()
    duration_ms = _as_int(payload.get("duration_ms"))

    if not session_id:
        return PostToolUseCapture(
            session_id="",
            tool_name=tool_name,
            turn_index=None,
            timestamp_ms=timestamp_ms,
            input_hash="",
            input_tokens_est=0,
            output_tokens_est=0,
            recorded=False,
            reason="missing_session_id",
        )

    tool_input = _tool_input_from_payload(payload)
    tool_response = _tool_response_from_payload(payload)
    turn_index = _as_int(payload.get("turn_index"))

    input_tokens_est = estimate_token_count(tool_input)
    output_tokens_est = estimate_token_count(tool_response)
    input_hash = _input_hash(tool_name, tool_input)

    try:
        if db_path is None:
            paths = ensure_runtime_dirs(resolve_runtime_paths())
            resolved_db_path = paths.db_path
        else:
            resolved_db_path = Path(db_path)
            resolved_db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(resolved_db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")

            if not _table_exists(conn, "tool_uses"):
                return PostToolUseCapture(
                    session_id=session_id,
                    tool_name=tool_name,
                    turn_index=turn_index,
                    timestamp_ms=timestamp_ms,
                    input_hash=input_hash,
                    input_tokens_est=input_tokens_est,
                    output_tokens_est=output_tokens_est,
                    recorded=False,
                    reason="tool_uses_table_missing",
                )

            _ensure_session_exists(
                conn,
                session_id=session_id,
                timestamp_ms=timestamp_ms,
            )

            if turn_index is None:
                turn_index = _latest_turn_index(conn, session_id)

            values: dict[str, SQLiteValue] = {
                "session_id": session_id,
                "turn_index": turn_index,
                "timestamp_ms": timestamp_ms,
                "tool_name": tool_name,
                "input_hash": input_hash,
                "input_size": payload_size_bytes(tool_input),
                "output_size": payload_size_bytes(tool_response),
                "success": 1,
                "duration_ms": duration_ms,
                "input_tokens_est": input_tokens_est,
                "output_tokens_est": output_tokens_est,
            }

            inserted = _insert_adaptive(conn, "tool_uses", values)

            if not inserted:
                return PostToolUseCapture(
                    session_id=session_id,
                    tool_name=tool_name,
                    turn_index=turn_index,
                    timestamp_ms=timestamp_ms,
                    input_hash=input_hash,
                    input_tokens_est=input_tokens_est,
                    output_tokens_est=output_tokens_est,
                    recorded=False,
                    reason="no_matching_tool_uses_columns",
                )

            _update_turn_tool_count(
                conn,
                session_id=session_id,
                turn_index=turn_index,
            )
            _update_session_token_totals(
                conn,
                session_id=session_id,
                input_tokens_est=input_tokens_est,
                output_tokens_est=output_tokens_est,
            )

            conn.commit()

    except Exception as exc:
        log_exception(exc, context="post_tool_use_capture")
        return PostToolUseCapture(
            session_id=session_id,
            tool_name=tool_name,
            turn_index=turn_index,
            timestamp_ms=timestamp_ms,
            input_hash=input_hash,
            input_tokens_est=input_tokens_est,
            output_tokens_est=output_tokens_est,
            recorded=False,
            reason="exception",
        )

    return PostToolUseCapture(
        session_id=session_id,
        tool_name=tool_name,
        turn_index=turn_index,
        timestamp_ms=timestamp_ms,
        input_hash=input_hash,
        input_tokens_est=input_tokens_est,
        output_tokens_est=output_tokens_est,
        recorded=True,
    )


def handle_post_tool_use(payload: object) -> PostToolUseCapture:
    """Entry point used by the hook wrapper."""

    return record_post_tool_use(_as_mapping(payload))
