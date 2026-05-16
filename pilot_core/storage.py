"""SQLite storage repositories for Pilot sessions and turns.

Day 11 introduces a small repository layer over the SQLite schema created in
the previous storage days.

This module intentionally focuses only on:
- sessions
- turns

Tool-use and signal repositories come next.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from pilot_core.constants import Defaults, SessionState, parse_session_state
from pilot_core.paths import ensure_runtime_dirs, resolve_runtime_paths


@dataclass(frozen=True)
class SessionRecord:
    """A row from the sessions table."""

    id: str
    started_at: int
    ended_at: int | None
    cwd: str | None
    model: str | None
    parent_session_id: str | None
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float
    state: SessionState
    handoff_summary_path: str | None


@dataclass(frozen=True)
class TurnRecord:
    """A row from the turns table."""

    id: int
    session_id: str | None
    turn_index: int
    started_at: int | None
    ended_at: int | None
    user_prompt_preview: str | None
    tool_count: int
    error_count: int


_STORAGE_SCHEMA: tuple[str, ...] = (
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
    """,
    """
    CREATE TABLE IF NOT EXISTS turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        turn_index INTEGER,
        started_at INTEGER,
        ended_at INTEGER,
        user_prompt_preview TEXT,
        tool_count INTEGER DEFAULT 0,
        error_count INTEGER DEFAULT 0,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_storage_sessions_started_at ON sessions(started_at);",
    "CREATE INDEX IF NOT EXISTS idx_storage_sessions_state ON sessions(state);",
    "CREATE INDEX IF NOT EXISTS idx_storage_turns_session ON turns(session_id, turn_index);",
)


def _state_value(state: SessionState | str) -> str:
    """Return a safe raw string for a session state."""

    if isinstance(state, SessionState):
        return state.value
    return parse_session_state(state).value


def _optional_str(value: object) -> str | None:
    """Convert SQLite nullable values into optional strings."""

    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    """Convert SQLite nullable values into optional integers."""

    if value is None:
        return None
    return _int_value(value)


def _int_value(value: object) -> int:
    """Convert SQLite values into integers."""

    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str | bytes | bytearray):
        return int(value)

    raise TypeError(f"Expected SQLite integer-compatible value, got {type(value).__name__}")


def _float_value(value: object) -> float:
    """Convert SQLite values into floats."""

    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str | bytes | bytearray):
        return float(value)

    raise TypeError(f"Expected SQLite float-compatible value, got {type(value).__name__}")


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with Pilot runtime pragmas."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute(f"PRAGMA busy_timeout = {Defaults.DB_BUSY_TIMEOUT_MS};")
    return connection


def bootstrap_storage_schema(connection: sqlite3.Connection) -> None:
    """Create the minimal storage schema needed by repositories.

    The migration layer remains the canonical owner of schema evolution. This
    helper is defensive and idempotent, which keeps repository tests and local
    smoke runs simple.
    """

    with connection:
        for statement in _STORAGE_SCHEMA:
            connection.execute(statement)


def _row_to_session(row: sqlite3.Row | None) -> SessionRecord | None:
    """Convert a SQLite row into a SessionRecord."""

    if row is None:
        return None

    return SessionRecord(
        id=str(row["id"]),
        started_at=_int_value(row["started_at"]),
        ended_at=_optional_int(row["ended_at"]),
        cwd=_optional_str(row["cwd"]),
        model=_optional_str(row["model"]),
        parent_session_id=_optional_str(row["parent_session_id"]),
        total_input_tokens=_int_value(row["total_input_tokens"]),
        total_output_tokens=_int_value(row["total_output_tokens"]),
        estimated_cost_usd=_float_value(row["estimated_cost_usd"]),
        state=parse_session_state(str(row["state"])),
        handoff_summary_path=_optional_str(row["handoff_summary_path"]),
    )


def _row_to_turn(row: sqlite3.Row | None) -> TurnRecord | None:
    """Convert a SQLite row into a TurnRecord."""

    if row is None:
        return None

    return TurnRecord(
        id=_int_value(row["id"]),
        session_id=_optional_str(row["session_id"]),
        turn_index=_int_value(row["turn_index"]),
        started_at=_optional_int(row["started_at"]),
        ended_at=_optional_int(row["ended_at"]),
        user_prompt_preview=_optional_str(row["user_prompt_preview"]),
        tool_count=_int_value(row["tool_count"]),
        error_count=_int_value(row["error_count"]),
    )


class SessionRepository:
    """Repository for session rows."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self,
        *,
        session_id: str,
        started_at: int,
        cwd: str | None = None,
        model: str | None = None,
        parent_session_id: str | None = None,
        state: SessionState | str = SessionState.HEALTHY,
    ) -> SessionRecord:
        """Create a session row if it does not already exist."""

        with self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO sessions (
                    id,
                    started_at,
                    cwd,
                    model,
                    parent_session_id,
                    state
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    session_id,
                    started_at,
                    cwd,
                    model,
                    parent_session_id,
                    _state_value(state),
                ),
            )

        return self.require(session_id)

    def get(self, session_id: str) -> SessionRecord | None:
        """Return a session by id, or None."""

        row = self._connection.execute(
            """
            SELECT
                id,
                started_at,
                ended_at,
                cwd,
                model,
                parent_session_id,
                total_input_tokens,
                total_output_tokens,
                estimated_cost_usd,
                state,
                handoff_summary_path
            FROM sessions
            WHERE id = ?;
            """,
            (session_id,),
        ).fetchone()

        return _row_to_session(row)

    def require(self, session_id: str) -> SessionRecord:
        """Return a session by id, or raise KeyError."""

        record = self.get(session_id)
        if record is None:
            raise KeyError(f"Session not found: {session_id}")
        return record

    def exists(self, session_id: str) -> bool:
        """Return True if a session exists."""

        row = self._connection.execute(
            "SELECT 1 FROM sessions WHERE id = ? LIMIT 1;",
            (session_id,),
        ).fetchone()
        return row is not None

    def list_recent(self, *, limit: int = 20) -> list[SessionRecord]:
        """Return recent sessions ordered by start time descending."""

        rows = self._connection.execute(
            """
            SELECT
                id,
                started_at,
                ended_at,
                cwd,
                model,
                parent_session_id,
                total_input_tokens,
                total_output_tokens,
                estimated_cost_usd,
                state,
                handoff_summary_path
            FROM sessions
            ORDER BY started_at DESC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()

        records: list[SessionRecord] = []
        for row in rows:
            record = _row_to_session(row)
            if record is not None:
                records.append(record)
        return records

    def update_state(self, session_id: str, state: SessionState | str) -> SessionRecord:
        """Update a session state."""

        with self._connection:
            self._connection.execute(
                "UPDATE sessions SET state = ? WHERE id = ?;",
                (_state_value(state), session_id),
            )

        return self.require(session_id)

    def end(self, session_id: str, *, ended_at: int) -> SessionRecord:
        """Mark a session as ended."""

        with self._connection:
            self._connection.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?;",
                (ended_at, session_id),
            )

        return self.require(session_id)

    def add_token_usage(
        self,
        session_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> SessionRecord:
        """Increment token and cost totals for a session."""

        with self._connection:
            self._connection.execute(
                """
                UPDATE sessions
                SET
                    total_input_tokens = total_input_tokens + ?,
                    total_output_tokens = total_output_tokens + ?,
                    estimated_cost_usd = estimated_cost_usd + ?
                WHERE id = ?;
                """,
                (input_tokens, output_tokens, estimated_cost_usd, session_id),
            )

        return self.require(session_id)

    def set_handoff_summary_path(
        self,
        session_id: str,
        handoff_summary_path: str | Path | None,
    ) -> SessionRecord:
        """Set the handoff summary path for a session."""

        path_value = None if handoff_summary_path is None else str(handoff_summary_path)

        with self._connection:
            self._connection.execute(
                "UPDATE sessions SET handoff_summary_path = ? WHERE id = ?;",
                (path_value, session_id),
            )

        return self.require(session_id)


class TurnRepository:
    """Repository for turn rows."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def start(
        self,
        *,
        session_id: str,
        turn_index: int,
        started_at: int,
        user_prompt_preview: str | None = None,
    ) -> TurnRecord:
        """Create or refresh a turn row."""

        existing = self.get(session_id=session_id, turn_index=turn_index)

        with self._connection:
            if existing is None:
                self._connection.execute(
                    """
                    INSERT INTO turns (
                        session_id,
                        turn_index,
                        started_at,
                        user_prompt_preview
                    )
                    VALUES (?, ?, ?, ?);
                    """,
                    (session_id, turn_index, started_at, user_prompt_preview),
                )
            else:
                self._connection.execute(
                    """
                    UPDATE turns
                    SET
                        started_at = ?,
                        ended_at = NULL,
                        user_prompt_preview = ?
                    WHERE session_id = ? AND turn_index = ?;
                    """,
                    (started_at, user_prompt_preview, session_id, turn_index),
                )

        return self.require(session_id=session_id, turn_index=turn_index)

    def get(self, *, session_id: str, turn_index: int) -> TurnRecord | None:
        """Return a turn by session id and index, or None."""

        row = self._connection.execute(
            """
            SELECT
                id,
                session_id,
                turn_index,
                started_at,
                ended_at,
                user_prompt_preview,
                tool_count,
                error_count
            FROM turns
            WHERE session_id = ? AND turn_index = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (session_id, turn_index),
        ).fetchone()

        return _row_to_turn(row)

    def require(self, *, session_id: str, turn_index: int) -> TurnRecord:
        """Return a turn by session id and index, or raise KeyError."""

        record = self.get(session_id=session_id, turn_index=turn_index)
        if record is None:
            raise KeyError(f"Turn not found: session={session_id!r}, turn_index={turn_index}")
        return record

    def latest(self, session_id: str) -> TurnRecord | None:
        """Return the latest turn for a session."""

        row = self._connection.execute(
            """
            SELECT
                id,
                session_id,
                turn_index,
                started_at,
                ended_at,
                user_prompt_preview,
                tool_count,
                error_count
            FROM turns
            WHERE session_id = ?
            ORDER BY turn_index DESC, id DESC
            LIMIT 1;
            """,
            (session_id,),
        ).fetchone()

        return _row_to_turn(row)

    def next_turn_index(self, session_id: str) -> int:
        """Return the next turn index for a session."""

        row = self._connection.execute(
            """
            SELECT COALESCE(MAX(turn_index), -1) + 1 AS next_turn_index
            FROM turns
            WHERE session_id = ?;
            """,
            (session_id,),
        ).fetchone()

        if row is None:
            return 0
        return _int_value(row["next_turn_index"])

    def end(self, *, session_id: str, turn_index: int, ended_at: int) -> TurnRecord:
        """Mark a turn as ended."""

        with self._connection:
            self._connection.execute(
                """
                UPDATE turns
                SET ended_at = ?
                WHERE session_id = ? AND turn_index = ?;
                """,
                (ended_at, session_id, turn_index),
            )

        return self.require(session_id=session_id, turn_index=turn_index)

    def increment_tool_count(
        self,
        *,
        session_id: str,
        turn_index: int,
        amount: int = 1,
    ) -> TurnRecord:
        """Increment the tool count for a turn."""

        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE turns
                SET tool_count = tool_count + ?
                WHERE session_id = ? AND turn_index = ?;
                """,
                (amount, session_id, turn_index),
            )

        if cursor.rowcount == 0:
            raise KeyError(f"Turn not found: session={session_id!r}, turn_index={turn_index}")

        return self.require(session_id=session_id, turn_index=turn_index)

    def increment_error_count(
        self,
        *,
        session_id: str,
        turn_index: int,
        amount: int = 1,
    ) -> TurnRecord:
        """Increment the error count for a turn."""

        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE turns
                SET error_count = error_count + ?
                WHERE session_id = ? AND turn_index = ?;
                """,
                (amount, session_id, turn_index),
            )

        if cursor.rowcount == 0:
            raise KeyError(f"Turn not found: session={session_id!r}, turn_index={turn_index}")

        return self.require(session_id=session_id, turn_index=turn_index)

    def list_for_session(self, session_id: str, *, limit: int | None = None) -> list[TurnRecord]:
        """Return turns for a session ordered by turn index."""

        sql = """
            SELECT
                id,
                session_id,
                turn_index,
                started_at,
                ended_at,
                user_prompt_preview,
                tool_count,
                error_count
            FROM turns
            WHERE session_id = ?
            ORDER BY turn_index ASC, id ASC
        """

        params: tuple[object, ...]
        if limit is None:
            sql = f"{sql};"
            params = (session_id,)
        else:
            sql = f"{sql} LIMIT ?;"
            params = (session_id, limit)

        rows = self._connection.execute(sql, params).fetchall()

        records: list[TurnRecord] = []
        for row in rows:
            record = _row_to_turn(row)
            if record is not None:
                records.append(record)
        return records


class PilotStorage:
    """Small storage facade exposing repositories over one SQLite connection."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            paths = ensure_runtime_dirs(resolve_runtime_paths())
            resolved_db_path = paths.db_path
        else:
            resolved_db_path = Path(db_path)

        self.db_path = resolved_db_path
        self.connection = _connect(resolved_db_path)
        bootstrap_storage_schema(self.connection)

        self.sessions = SessionRepository(self.connection)
        self.turns = TurnRepository(self.connection)

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self.connection.close()

    def __enter__(self) -> PilotStorage:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def open_storage(db_path: str | Path | None = None) -> PilotStorage:
    """Open a PilotStorage instance."""

    return PilotStorage(db_path=db_path)


def get_storage(db_path: str | Path | None = None) -> PilotStorage:
    """Compatibility alias for opening storage."""

    return open_storage(db_path=db_path)


def get_db(db_path: str | Path | None = None) -> PilotStorage:
    """Compatibility alias used by future hook code."""

    return open_storage(db_path=db_path)


@contextmanager
def storage_context(db_path: str | Path | None = None) -> Iterator[PilotStorage]:
    """Context manager for short-lived storage work."""

    storage = open_storage(db_path=db_path)
    try:
        yield storage
    finally:
        storage.close()
