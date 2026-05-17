"""SessionStart hook handler.

This module contains the testable core logic for the Claude Code SessionStart
hook. The public script in hooks/session_start.py should stay thin and
fail-silent.

Responsibilities:
- Parse SessionStart payloads from Claude Code.
- Create or reopen a session row in SQLite.
- Preserve parent session linkage when available.
- Never raise errors to the hook process.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from pilot_core.constants import SessionState
from pilot_core.paths import RuntimePaths, ensure_runtime_dirs, resolve_runtime_paths
from pilot_core.safety import log_exception


@dataclass(frozen=True)
class SessionStartPayload:
    """Normalised SessionStart payload."""

    session_id: str
    started_at_ms: int
    cwd: str | None = None
    model: str | None = None
    parent_session_id: str | None = None


def now_ms() -> int:
    """Return current Unix time in milliseconds."""

    return int(time.time() * 1000)


def _first_string(data: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty string found in a payload."""

    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _timestamp_ms(data: Mapping[str, Any]) -> int:
    """Read timestamp_ms from hook payload, falling back to current time."""

    raw_value = data.get("timestamp_ms", data.get("timestampMs"))

    if isinstance(raw_value, int):
        return raw_value

    if isinstance(raw_value, float):
        return int(raw_value)

    if isinstance(raw_value, str) and raw_value.strip():
        try:
            return int(float(raw_value))
        except ValueError:
            return now_ms()

    return now_ms()


def parse_session_start_payload(data: Mapping[str, Any]) -> SessionStartPayload:
    """Parse and validate a raw Claude Code SessionStart payload."""

    session_id = _first_string(data, ("session_id", "sessionId", "id"))
    if session_id is None:
        msg = "SessionStart payload is missing session_id"
        raise ValueError(msg)

    cwd = _first_string(data, ("cwd", "workspace_dir", "workspaceDir", "project_dir", "projectDir"))
    model = _first_string(data, ("model", "model_name", "modelName"))
    parent_session_id = _first_string(
        data,
        (
            "parent_session_id",
            "parentSessionId",
            "parent_id",
            "parentId",
            "resume_session_id",
            "resumeSessionId",
        ),
    )

    return SessionStartPayload(
        session_id=session_id,
        started_at_ms=_timestamp_ms(data),
        cwd=cwd,
        model=model,
        parent_session_id=parent_session_id,
    )


def load_hook_payload(text: str) -> dict[str, Any]:
    """Load a hook payload from stdin text.

    Empty stdin is treated as an empty payload so the hook can fail silently.
    """

    stripped = text.strip()
    if not stripped:
        return {}

    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        msg = "SessionStart payload must be a JSON object"
        raise TypeError(msg)

    return payload


def connect_database(db_path: Path) -> sqlite3.Connection:
    """Open the Pilot SQLite database with runtime pragmas."""

    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA busy_timeout = 5000;")
    return connection


def record_session_start(connection: sqlite3.Connection, payload: SessionStartPayload) -> None:
    """Insert or reopen a session row.

    The operation is idempotent. Repeated SessionStart events for the same
    session update lightweight metadata but keep the original started_at.
    """

    connection.execute(
        """
        INSERT INTO sessions (
            id,
            started_at,
            ended_at,
            cwd,
            model,
            parent_session_id,
            state
        )
        VALUES (?, ?, NULL, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            ended_at = NULL,
            cwd = COALESCE(excluded.cwd, sessions.cwd),
            model = COALESCE(excluded.model, sessions.model),
            parent_session_id = COALESCE(
                excluded.parent_session_id,
                sessions.parent_session_id
            );
        """,
        (
            payload.session_id,
            payload.started_at_ms,
            payload.cwd,
            payload.model,
            payload.parent_session_id,
            SessionState.HEALTHY.value,
        ),
    )
    connection.commit()


def handle_session_start(
    data: Mapping[str, Any],
    *,
    paths: RuntimePaths | None = None,
    debug_context: str = "session_start",
) -> bool:
    """Handle a SessionStart payload.

    Returns True if a session row was recorded. Returns False if anything went
    wrong. Exceptions are logged and swallowed by design.
    """

    try:
        payload = parse_session_start_payload(data)
        runtime_paths = ensure_runtime_dirs(paths or resolve_runtime_paths())

        with connect_database(runtime_paths.db_path) as connection:
            record_session_start(connection, payload)

        return True
    except Exception as exc:
        log_exception(exc, context=debug_context)
        return False


def main(stdin: TextIO | None = None) -> int:
    """CLI entrypoint used by hooks/session_start.py."""

    input_stream = stdin or sys.stdin

    try:
        data = load_hook_payload(input_stream.read())
        handle_session_start(data)
    except Exception as exc:
        log_exception(exc, context="session_start.main")

    return 0
