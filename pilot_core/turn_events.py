"""Turn-level event helpers for Claude Code hook payloads.

Day 17 owns UserPromptSubmit tracking:
- read session_id and prompt from the hook payload
- create the session row if it is missing
- close any previous open turn for the same session
- insert a new turn with a monotonically increasing turn_index
- reset per-turn counters through tool_count=0 and error_count=0
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pilot_core.constants import SessionState
from pilot_core.paths import ensure_runtime_dirs, resolve_runtime_paths

PROMPT_PREVIEW_LIMIT = 200


@dataclass(frozen=True)
class UserPromptTurn:
    """Result of recording a UserPromptSubmit event."""

    session_id: str
    turn_index: int
    prompt_preview: str
    started_at: int


def current_time_ms() -> int:
    """Return current Unix time in milliseconds."""

    return int(time.time() * 1000)


def prompt_preview(prompt: object, *, limit: int = PROMPT_PREVIEW_LIMIT) -> str:
    """Return a compact prompt preview safe for SQLite storage."""

    if prompt is None:
        return ""

    text = " ".join(str(prompt).split())
    return text[:limit]


def _required_text(payload: Mapping[str, object], key: str) -> str:
    """Read a required non-empty text field from a hook payload."""

    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Missing required hook payload field: {key}"
        raise ValueError(msg)
    return value


def _optional_text(payload: Mapping[str, object], key: str) -> str | None:
    """Read an optional text field from a hook payload."""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with Pilot runtime pragmas."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA busy_timeout = 5000;")
    return connection


def _ensure_minimal_tables(connection: sqlite3.Connection) -> None:
    """Create the minimal Day 17 tables if a hook runs before full bootstrap.

    The full schema and migrations still own the canonical database layout.
    These CREATE TABLE IF NOT EXISTS statements are defensive so the hook can
    fail safely during early local smoke tests.
    """

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            cwd TEXT,
            model TEXT,
            parent_session_id TEXT,
            total_input_tokens INTEGER DEFAULT 0,
            total_output_tokens INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0,
            state TEXT DEFAULT 'healthy',
            handoff_summary_path TEXT
        );
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_index INTEGER NOT NULL,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            user_prompt_preview TEXT,
            tool_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_turns_session
        ON turns(session_id, turn_index);
        """
    )


def _next_turn_index(connection: sqlite3.Connection, session_id: str) -> int:
    """Return the next turn index for a session."""

    row = connection.execute(
        """
        SELECT COALESCE(MAX(turn_index), -1) + 1
        FROM turns
        WHERE session_id = ?;
        """,
        (session_id,),
    ).fetchone()

    if row is None or row[0] is None:
        return 0

    return int(row[0])


def record_user_prompt_turn(
    payload: Mapping[str, object],
    *,
    db_path: str | Path | None = None,
    now_ms: int | None = None,
) -> UserPromptTurn:
    """Record a UserPromptSubmit hook payload as a new turn."""

    session_id = _required_text(payload, "session_id")
    cwd = _optional_text(payload, "cwd")
    started_at = current_time_ms() if now_ms is None else now_ms
    preview = prompt_preview(payload.get("prompt"))

    if db_path is None:
        paths = ensure_runtime_dirs(resolve_runtime_paths())
        resolved_db_path = paths.db_path
    else:
        resolved_db_path = Path(db_path)

    with _connect(resolved_db_path) as connection:
        _ensure_minimal_tables(connection)

        connection.execute(
            """
            INSERT OR IGNORE INTO sessions (id, started_at, cwd, state)
            VALUES (?, ?, ?, ?);
            """,
            (session_id, started_at, cwd, str(SessionState.HEALTHY)),
        )

        connection.execute(
            """
            UPDATE turns
            SET ended_at = ?
            WHERE session_id = ?
              AND ended_at IS NULL;
            """,
            (started_at, session_id),
        )

        turn_index = _next_turn_index(connection, session_id)

        connection.execute(
            """
            INSERT INTO turns (
                session_id,
                turn_index,
                started_at,
                user_prompt_preview,
                tool_count,
                error_count
            )
            VALUES (?, ?, ?, ?, 0, 0);
            """,
            (session_id, turn_index, started_at, preview),
        )

    return UserPromptTurn(
        session_id=session_id,
        turn_index=turn_index,
        prompt_preview=preview,
        started_at=started_at,
    )
