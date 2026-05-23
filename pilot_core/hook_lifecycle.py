"""Lifecycle helpers for Stop and SessionEnd hooks."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pilot_core.constants import SessionState, parse_session_state, should_prepare_handoff
from pilot_core.paths import RuntimePaths, ensure_runtime_dirs, resolve_runtime_paths
from pilot_core.safety import safe_string, write_debug_log


@dataclass(frozen=True)
class LifecycleResult:
    """Result produced by Stop and SessionEnd hook processing."""

    event: str
    session_id: str
    handoff_path: Path | None
    ended: bool
    additional_context: str | None = None

    def stdout_payload(self) -> dict[str, str]:
        """Return hook stdout JSON payload."""

        if not self.additional_context:
            return {}
        return {"additionalContext": self.additional_context}


def now_ms() -> int:
    """Return current UTC timestamp in milliseconds."""

    return int(datetime.now(timezone.utc).timestamp() * 1000)


def extract_session_id(payload: Mapping[str, Any]) -> str:
    """Extract a required session id from a hook payload."""

    raw_session_id = payload.get("session_id") or payload.get("sessionId")
    if isinstance(raw_session_id, str) and raw_session_id.strip():
        return raw_session_id.strip()

    raise ValueError("Hook payload is missing a non-empty session_id")


def _payload_str(payload: Mapping[str, Any], key: str, default: str | None = None) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _safe_file_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return cleaned[:120] or "unknown-session"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?;",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()

    rows = conn.execute(f"PRAGMA table_info({table_name});").fetchall()
    return {str(row["name"]) for row in rows}


def _session_key_column(columns: set[str]) -> str | None:
    if "id" in columns:
        return "id"
    if "session_id" in columns:
        return "session_id"
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {str(key): row[key] for key in keys}


def _get_session_row(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    columns = _table_columns(conn, "sessions")
    key_column = _session_key_column(columns)
    if key_column is None:
        return None

    row = conn.execute(
        f"SELECT * FROM sessions WHERE {key_column} = ?;",
        (session_id,),
    ).fetchone()

    if not isinstance(row, sqlite3.Row):
        return None

    return _row_to_dict(row)


def _ensure_session_row(
    conn: sqlite3.Connection,
    session_id: str,
    payload: Mapping[str, Any],
) -> None:
    columns = _table_columns(conn, "sessions")
    key_column = _session_key_column(columns)
    if key_column is None:
        return

    if _get_session_row(conn, session_id) is not None:
        return

    values: dict[str, Any] = {key_column: session_id}

    if "started_at" in columns:
        values["started_at"] = now_ms()
    if "cwd" in columns:
        values["cwd"] = _payload_str(payload, "cwd", "")
    if "model" in columns:
        values["model"] = _payload_str(payload, "model", "")
    if "state" in columns:
        values["state"] = SessionState.HEALTHY.value

    column_sql = ", ".join(values)
    placeholder_sql = ", ".join("?" for _ in values)

    conn.execute(
        f"INSERT INTO sessions ({column_sql}) VALUES ({placeholder_sql});",
        tuple(values.values()),
    )


def _update_session(
    conn: sqlite3.Connection,
    session_id: str,
    values: Mapping[str, Any],
) -> None:
    columns = _table_columns(conn, "sessions")
    key_column = _session_key_column(columns)
    if key_column is None:
        return

    updates: list[str] = []
    params: list[Any] = []

    for column, value in values.items():
        if column in columns:
            updates.append(f"{column} = ?")
            params.append(value)

    if not updates:
        return

    params.append(session_id)
    conn.execute(
        f"UPDATE sessions SET {', '.join(updates)} WHERE {key_column} = ?;",
        tuple(params),
    )


def _session_state(row: Mapping[str, Any] | None) -> SessionState | None:
    if row is None:
        return None

    raw_state = row.get("state")
    if raw_state is None:
        return None

    try:
        return parse_session_state(str(raw_state))
    except ValueError:
        return None


def _should_emit_handoff_context(row: Mapping[str, Any] | None) -> bool:
    state = _session_state(row)
    if state is None:
        return False
    return should_prepare_handoff(state)


def _write_handoff_placeholder(
    *,
    paths: RuntimePaths,
    session_id: str,
    event: str,
    payload: Mapping[str, Any],
    state: SessionState | None,
) -> Path:
    handoff_path = paths.handoff_dir / f"{_safe_file_stem(session_id)}.md"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload_preview = safe_string(dict(payload), limit=1_500)
    state_value = state.value if state is not None else "unknown"

    content = f"""# Pilot Handoff Placeholder

## Session
- Session ID: `{session_id}`
- Event: `{event}`
- State at write time: `{state_value}`
- Generated at: `{timestamp}`

## Status
This is a Day 21 lifecycle placeholder.

The full handoff generator is scheduled for the later handoff milestone. For now,
Pilot proves that Stop and SessionEnd hooks can safely persist a resumable marker
without breaking the user's session.

## Next Implementation Step
Use this placeholder as the persistence target when the real signal engine and
handoff renderer become available.

## Payload Preview
{json.dumps(payload_preview, ensure_ascii=False)}
"""

    handoff_path.write_text(content, encoding="utf-8")
    return handoff_path


def process_stop_payload(
    payload: Mapping[str, Any],
    *,
    paths: RuntimePaths | None = None,
) -> LifecycleResult:
    """Process a Stop hook payload."""

    resolved_paths = ensure_runtime_dirs(paths or resolve_runtime_paths())
    session_id = extract_session_id(payload)
    conn = _connect(resolved_paths.db_path)

    try:
        _ensure_session_row(conn, session_id, payload)
        row_before = _get_session_row(conn, session_id)
        state_before = _session_state(row_before)

        handoff_path = _write_handoff_placeholder(
            paths=resolved_paths,
            session_id=session_id,
            event="Stop",
            payload=payload,
            state=state_before,
        )

        updates: dict[str, Any] = {
            "handoff_summary_path": str(handoff_path),
        }

        additional_context: str | None = None
        if _should_emit_handoff_context(row_before):
            updates["state"] = SessionState.HANDOFF_PENDING.value
            additional_context = (
                "[Pilot detected a session that may need handoff]\n"
                f"- Session: {session_id}\n"
                f"- Handoff placeholder: {handoff_path}\n"
                "Consider summarizing progress before continuing."
            )

        _update_session(conn, session_id, updates)
        conn.commit()
    finally:
        conn.close()

    write_debug_log(f"[stop] processed session_id={session_id} handoff={handoff_path}")

    return LifecycleResult(
        event="Stop",
        session_id=session_id,
        handoff_path=handoff_path,
        ended=False,
        additional_context=additional_context,
    )


def process_session_end_payload(
    payload: Mapping[str, Any],
    *,
    paths: RuntimePaths | None = None,
) -> LifecycleResult:
    """Process a SessionEnd hook payload."""

    resolved_paths = ensure_runtime_dirs(paths or resolve_runtime_paths())
    session_id = extract_session_id(payload)
    conn = _connect(resolved_paths.db_path)

    try:
        _ensure_session_row(conn, session_id, payload)
        row_before = _get_session_row(conn, session_id)
        state_before = _session_state(row_before)

        handoff_path = _write_handoff_placeholder(
            paths=resolved_paths,
            session_id=session_id,
            event="SessionEnd",
            payload=payload,
            state=state_before,
        )

        _update_session(
            conn,
            session_id,
            {
                "ended_at": now_ms(),
                "handoff_summary_path": str(handoff_path),
            },
        )
        conn.commit()
    finally:
        conn.close()

    write_debug_log(f"[session_end] processed session_id={session_id} handoff={handoff_path}")

    return LifecycleResult(
        event="SessionEnd",
        session_id=session_id,
        handoff_path=handoff_path,
        ended=True,
        additional_context=None,
    )
