"""SQLite storage repositories for Pilot sessions and turns.

Day 11 introduces a small repository layer over the SQLite schema created in
the previous storage days.

This module intentionally focuses only on:
- sessions
- turns

Tool-use and signal repositories come next.
"""

from __future__ import annotations

import hashlib as _day12_hashlib
import json as _day12_json
import sqlite3
import sqlite3 as _day12_sqlite3
from collections.abc import Iterator
from collections.abc import Iterator as _Day12Iterator
from contextlib import contextmanager
from contextlib import contextmanager as _day12_contextmanager
from dataclasses import dataclass
from dataclasses import dataclass as _day12_dataclass
from pathlib import Path
from pathlib import Path as _Day12Path
from time import time as _day12_time
from types import TracebackType
from typing import Any as _Day12Any

from pilot_core.constants import Defaults, SessionState, parse_session_state
from pilot_core.paths import ensure_runtime_dirs, resolve_runtime_paths
from pilot_core.paths import ensure_runtime_dirs as _day12_ensure_runtime_dirs
from pilot_core.paths import resolve_runtime_paths as _day12_resolve_runtime_paths


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
        return _day12_to_int(value)
    if isinstance(value, str | bytes | bytearray):
        return _day12_to_int(value)

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


# --- Day 12 storage repositories start ---


@_day12_dataclass(frozen=True)
class ToolUseCreate:
    """Input payload for creating a tool-use event."""

    session_id: str
    tool_name: str
    turn_index: int | None = None
    timestamp_ms: int | None = None
    input_hash: str | None = None
    input_size: int | None = None
    output_size: int | None = None
    success: bool = True
    duration_ms: int | None = None
    input_tokens_est: int = 0
    output_tokens_est: int = 0
    input_payload: _Day12Any | None = None
    output_payload: _Day12Any | None = None


@_day12_dataclass(frozen=True)
class ToolUseRecord:
    """Stored tool-use event."""

    id: int
    session_id: str
    turn_index: int | None
    timestamp_ms: int
    tool_name: str
    input_hash: str
    input_size: int
    output_size: int
    success: bool
    duration_ms: int | None
    input_tokens_est: int
    output_tokens_est: int


@_day12_dataclass(frozen=True)
class SignalEventCreate:
    """Input payload for creating a signal event."""

    session_id: str
    signal_type: str
    score: float
    timestamp_ms: int | None = None
    health_score: float | None = None
    state_before: str | None = None
    state_after: str | None = None
    metadata: dict[str, _Day12Any] | None = None


@_day12_dataclass(frozen=True)
class SignalEventRecord:
    """Stored signal event."""

    id: int
    session_id: str
    timestamp_ms: int
    signal_type: str
    score: float
    health_score: float | None
    state_before: str | None
    state_after: str | None
    metadata_json: str | None


@_day12_dataclass(frozen=True)
class StorageRepositories:
    """Convenience bundle for storage repositories."""

    tool_uses: ToolUseRepository
    signals: SignalEventRepository


def _day12_now_ms() -> int:
    """Return current unix time in milliseconds."""

    return int(_day12_time() * 1000)


def _day12_resolve_db_path(db_path: str | _Day12Path | None = None) -> _Day12Path:
    """Resolve the SQLite DB path used by Day 12 repositories."""

    if db_path is not None:
        return _Day12Path(db_path)

    paths = _day12_ensure_runtime_dirs(_day12_resolve_runtime_paths())
    return paths.db_path


def _day12_open_connection(
    db_path: str | _Day12Path | None = None,
    *,
    ensure_schema: bool = True,
) -> _day12_sqlite3.Connection:
    """Open a SQLite connection with Pilot runtime pragmas."""

    path = _day12_resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = _day12_sqlite3.connect(str(path))
    connection.row_factory = _day12_sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON;")
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA busy_timeout=5000;")

    if ensure_schema:
        ensure_storage_schema(connection=connection)

    return connection


def ensure_storage_schema(
    db_path: str | _Day12Path | None = None,
    *,
    connection: _day12_sqlite3.Connection | None = None,
) -> None:
    """Ensure the storage tables needed by Day 12 repositories exist.

    This is intentionally additive. It does not replace the migration system.
    It gives tests and local smoke checks a safe schema baseline.
    """

    owns_connection = connection is None
    conn = connection or _day12_open_connection(db_path, ensure_schema=False)

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL DEFAULT 0,
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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_index INTEGER,
                timestamp_ms INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                input_size INTEGER NOT NULL DEFAULT 0,
                output_size INTEGER NOT NULL DEFAULT 0,
                success INTEGER NOT NULL DEFAULT 1,
                duration_ms INTEGER,
                input_tokens_est INTEGER NOT NULL DEFAULT 0,
                output_tokens_est INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_uses_session
            ON tool_uses(session_id, timestamp_ms);
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_uses_hash
            ON tool_uses(session_id, input_hash);
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                signal_type TEXT NOT NULL,
                score REAL NOT NULL,
                health_score REAL,
                state_before TEXT,
                state_after TEXT,
                metadata_json TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_signals_session
            ON signals(session_id, timestamp_ms);
            """
        )

        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


@_day12_contextmanager
def storage_transaction(
    db_path: str | _Day12Path | None = None,
    *,
    connection: _day12_sqlite3.Connection | None = None,
) -> _Day12Iterator[_day12_sqlite3.Connection]:
    """Run a SQLite transaction with commit/rollback handling."""

    owns_connection = connection is None
    conn = connection or _day12_open_connection(db_path)

    try:
        yield conn
        if owns_connection:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


def _day12_table_columns(conn: _day12_sqlite3.Connection, table_name: str) -> set[str]:
    """Return available columns for a table."""

    rows = conn.execute(f"PRAGMA table_info({table_name});").fetchall()
    return {str(row["name"]) for row in rows}


def _day12_insert_row(
    conn: _day12_sqlite3.Connection,
    table_name: str,
    values: dict[str, _Day12Any],
) -> int:
    """Insert values into a table, ignoring keys missing from the current schema."""

    available_columns = _day12_table_columns(conn, table_name)
    filtered = {
        key: value
        for key, value in values.items()
        if key in available_columns and value is not None
    }

    if not filtered:
        msg = f"No insertable values for table {table_name!r}"
        raise ValueError(msg)

    columns = tuple(filtered)
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    params = tuple(filtered[column] for column in columns)

    cursor = conn.execute(
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders});",
        params,
    )
    lastrowid = cursor.lastrowid
    if lastrowid is None:
        raise RuntimeError("SQLite insert did not return a row id.")
    return lastrowid


def _day12_stable_json(value: _Day12Any) -> str:
    """Return stable JSON text for hashing and logging."""

    return _day12_json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _day12_payload_hash(value: _Day12Any) -> str:
    """Hash a tool input payload for repeated-call detection."""

    text = _day12_stable_json(value)
    return _day12_hashlib.sha256(text.encode("utf-8")).hexdigest()


def _day12_payload_size(value: _Day12Any) -> int:
    """Estimate payload size in characters/bytes."""

    if value is None:
        return 0
    if isinstance(value, str | bytes | bytearray):
        return len(value)
    return len(_day12_stable_json(value))


def _day12_bool_to_int(value: bool) -> int:
    """Convert bool to SQLite-friendly integer."""

    return 1 if value else 0


def _day12_to_int(value: object, *, default: int = 0) -> int:
    """Convert a SQLite value to int in a mypy-safe way."""

    if value is None:
        return default

    if isinstance(value, bool):
        return 1 if value else 0

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value)

    if isinstance(value, str | bytes | bytearray):
        return int(value)

    return int(str(value))


def _day12_row_has(row: _day12_sqlite3.Row, name: str) -> bool:
    """Return True when a sqlite row has a column."""

    return name in tuple(row.keys())


def _day12_row_optional_int(
    row: _day12_sqlite3.Row,
    name: str,
    *,
    default: int | None = None,
) -> int | None:
    """Read an optional integer from a sqlite row."""

    if not _day12_row_has(row, name):
        return default

    raw_value = row[name]
    if raw_value is None:
        return default

    return _day12_to_int(raw_value)


def _day12_row_int(row: _day12_sqlite3.Row, name: str, *, default: int = 0) -> int:
    """Read an integer from a sqlite row."""

    value = _day12_row_optional_int(row, name, default=None)
    if value is None:
        return default
    return value


def _day12_row_optional_float(
    row: _day12_sqlite3.Row,
    name: str,
    *,
    default: float | None = None,
) -> float | None:
    """Read an optional float from a sqlite row."""

    if not _day12_row_has(row, name):
        return default
    value = row[name]
    if value is None:
        return default
    return float(value)


def _day12_row_float(row: _day12_sqlite3.Row, name: str, *, default: float = 0.0) -> float:
    """Read a float from a sqlite row."""

    value = _day12_row_optional_float(row, name, default=default)
    return default if value is None else value


def _day12_row_optional_str(row: _day12_sqlite3.Row, name: str) -> str | None:
    """Read an optional string from a sqlite row."""

    if not _day12_row_has(row, name):
        return None
    value = row[name]
    if value is None:
        return None
    return str(value)


def _day12_row_str(row: _day12_sqlite3.Row, name: str, *, default: str = "") -> str:
    """Read a string from a sqlite row."""

    value = _day12_row_optional_str(row, name)
    return default if value is None else value


def _day12_tool_use_from_row(row: _day12_sqlite3.Row) -> ToolUseRecord:
    """Convert a sqlite row into a ToolUseRecord."""

    success_value = _day12_row_optional_int(row, "success", default=1)

    return ToolUseRecord(
        id=_day12_row_int(row, "id"),
        session_id=_day12_row_str(row, "session_id"),
        turn_index=_day12_row_optional_int(row, "turn_index"),
        timestamp_ms=_day12_row_int(row, "timestamp_ms"),
        tool_name=_day12_row_str(row, "tool_name"),
        input_hash=_day12_row_str(row, "input_hash"),
        input_size=_day12_row_int(row, "input_size"),
        output_size=_day12_row_int(row, "output_size"),
        success=bool(success_value),
        duration_ms=_day12_row_optional_int(row, "duration_ms"),
        input_tokens_est=_day12_row_int(row, "input_tokens_est"),
        output_tokens_est=_day12_row_int(row, "output_tokens_est"),
    )


def _day12_signal_event_from_row(row: _day12_sqlite3.Row) -> SignalEventRecord:
    """Convert a sqlite row into a SignalEventRecord."""

    return SignalEventRecord(
        id=_day12_row_int(row, "id"),
        session_id=_day12_row_str(row, "session_id"),
        timestamp_ms=_day12_row_int(row, "timestamp_ms"),
        signal_type=_day12_row_str(row, "signal_type"),
        score=_day12_row_float(row, "score"),
        health_score=_day12_row_optional_float(row, "health_score"),
        state_before=_day12_row_optional_str(row, "state_before"),
        state_after=_day12_row_optional_str(row, "state_after"),
        metadata_json=_day12_row_optional_str(row, "metadata_json"),
    )


class ToolUseRepository:
    """Repository for tool-use events."""

    def __init__(
        self,
        db_path: str | _Day12Path | None = None,
        *,
        connection: _day12_sqlite3.Connection | None = None,
    ) -> None:
        self.db_path = db_path
        self.connection = connection
        ensure_storage_schema(db_path, connection=connection)

    def insert(self, record: ToolUseCreate) -> int:
        """Insert a tool-use event and return its row id."""

        timestamp_ms = record.timestamp_ms if record.timestamp_ms is not None else _day12_now_ms()
        input_hash = record.input_hash or _day12_payload_hash(record.input_payload)

        values = {
            "session_id": record.session_id,
            "turn_index": record.turn_index,
            "timestamp_ms": timestamp_ms,
            "tool_name": record.tool_name,
            "input_hash": input_hash,
            "input_size": record.input_size
            if record.input_size is not None
            else _day12_payload_size(record.input_payload),
            "output_size": record.output_size
            if record.output_size is not None
            else _day12_payload_size(record.output_payload),
            "success": _day12_bool_to_int(record.success),
            "duration_ms": record.duration_ms,
            "input_tokens_est": record.input_tokens_est,
            "output_tokens_est": record.output_tokens_est,
        }

        if self.connection is not None:
            return _day12_insert_row(self.connection, "tool_uses", values)

        with storage_transaction(self.db_path) as conn:
            return _day12_insert_row(conn, "tool_uses", values)

    def list_for_session(
        self,
        session_id: str,
        *,
        limit: int = 100,
    ) -> list[ToolUseRecord]:
        """List tool-use events for a session."""

        owns_connection = self.connection is None
        conn = self.connection or _day12_open_connection(self.db_path)

        try:
            rows = conn.execute(
                """
                SELECT *
                FROM tool_uses
                WHERE session_id = ?
                ORDER BY timestamp_ms ASC, id ASC
                LIMIT ?;
                """,
                (session_id, limit),
            ).fetchall()
            return [_day12_tool_use_from_row(row) for row in rows]
        finally:
            if owns_connection:
                conn.close()

    def recent_for_session(
        self,
        session_id: str,
        *,
        limit: int = 10,
    ) -> list[ToolUseRecord]:
        """List recent tool-use events newest first."""

        owns_connection = self.connection is None
        conn = self.connection or _day12_open_connection(self.db_path)

        try:
            rows = conn.execute(
                """
                SELECT *
                FROM tool_uses
                WHERE session_id = ?
                ORDER BY timestamp_ms DESC, id DESC
                LIMIT ?;
                """,
                (session_id, limit),
            ).fetchall()
            return [_day12_tool_use_from_row(row) for row in rows]
        finally:
            if owns_connection:
                conn.close()

    def count_repeated(
        self,
        *,
        session_id: str,
        tool_name: str,
        input_hash: str,
        window_size: int = 10,
    ) -> int:
        """Count matching tool calls inside the most recent N tool-use events."""

        owns_connection = self.connection is None
        conn = self.connection or _day12_open_connection(self.db_path)

        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT tool_name, input_hash
                    FROM tool_uses
                    WHERE session_id = ?
                    ORDER BY timestamp_ms DESC, id DESC
                    LIMIT ?
                )
                WHERE tool_name = ? AND input_hash = ?;
                """,
                (session_id, window_size, tool_name, input_hash),
            ).fetchone()
            if row is None:
                return 0

            raw_count = row["count"]
            if raw_count is None:
                return 0

            return _day12_to_int(raw_count)
        finally:
            if owns_connection:
                conn.close()

    def count_recent_failures(
        self,
        *,
        session_id: str,
        window_size: int = 5,
    ) -> int:
        """Count failed tool calls in the most recent N events."""

        owns_connection = self.connection is None
        conn = self.connection or _day12_open_connection(self.db_path)

        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT success
                    FROM tool_uses
                    WHERE session_id = ?
                    ORDER BY timestamp_ms DESC, id DESC
                    LIMIT ?
                )
                WHERE success = 0;
                """,
                (session_id, window_size),
            ).fetchone()
            if row is None:
                return 0

            raw_count = row["count"]
            if raw_count is None:
                return 0

            return _day12_to_int(raw_count)
        finally:
            if owns_connection:
                conn.close()


class SignalEventRepository:
    """Repository for signal evaluation events."""

    def __init__(
        self,
        db_path: str | _Day12Path | None = None,
        *,
        connection: _day12_sqlite3.Connection | None = None,
    ) -> None:
        self.db_path = db_path
        self.connection = connection
        ensure_storage_schema(db_path, connection=connection)

    def insert(self, record: SignalEventCreate) -> int:
        """Insert a signal event and return its row id."""

        values = {
            "session_id": record.session_id,
            "timestamp_ms": record.timestamp_ms
            if record.timestamp_ms is not None
            else _day12_now_ms(),
            "signal_type": record.signal_type,
            "score": record.score,
            "health_score": record.health_score,
            "state_before": record.state_before,
            "state_after": record.state_after,
            "metadata_json": _day12_stable_json(record.metadata)
            if record.metadata is not None
            else None,
        }

        if self.connection is not None:
            return _day12_insert_row(self.connection, "signals", values)

        with storage_transaction(self.db_path) as conn:
            return _day12_insert_row(conn, "signals", values)

    def list_for_session(
        self,
        session_id: str,
        *,
        limit: int = 100,
    ) -> list[SignalEventRecord]:
        """List signal events for a session."""

        owns_connection = self.connection is None
        conn = self.connection or _day12_open_connection(self.db_path)

        try:
            rows = conn.execute(
                """
                SELECT *
                FROM signals
                WHERE session_id = ?
                ORDER BY timestamp_ms ASC, id ASC
                LIMIT ?;
                """,
                (session_id, limit),
            ).fetchall()
            return [_day12_signal_event_from_row(row) for row in rows]
        finally:
            if owns_connection:
                conn.close()

    def latest_for_session(
        self,
        session_id: str,
        *,
        limit: int = 10,
    ) -> list[SignalEventRecord]:
        """List recent signal events newest first."""

        owns_connection = self.connection is None
        conn = self.connection or _day12_open_connection(self.db_path)

        try:
            rows = conn.execute(
                """
                SELECT *
                FROM signals
                WHERE session_id = ?
                ORDER BY timestamp_ms DESC, id DESC
                LIMIT ?;
                """,
                (session_id, limit),
            ).fetchall()
            return [_day12_signal_event_from_row(row) for row in rows]
        finally:
            if owns_connection:
                conn.close()


def get_storage_repositories(
    db_path: str | _Day12Path | None = None,
    *,
    connection: _day12_sqlite3.Connection | None = None,
) -> StorageRepositories:
    """Return repository objects sharing the same DB target."""

    return StorageRepositories(
        tool_uses=ToolUseRepository(db_path, connection=connection),
        signals=SignalEventRepository(db_path, connection=connection),
    )


def record_tool_use(
    *,
    session_id: str,
    tool_name: str,
    input_payload: _Day12Any | None = None,
    output_payload: _Day12Any | None = None,
    turn_index: int | None = None,
    timestamp_ms: int | None = None,
    success: bool = True,
    duration_ms: int | None = None,
    input_tokens_est: int = 0,
    output_tokens_est: int = 0,
    db_path: str | _Day12Path | None = None,
) -> int:
    """Convenience helper for recording a tool-use event."""

    repository = ToolUseRepository(db_path)
    return repository.insert(
        ToolUseCreate(
            session_id=session_id,
            turn_index=turn_index,
            timestamp_ms=timestamp_ms,
            tool_name=tool_name,
            success=success,
            duration_ms=duration_ms,
            input_tokens_est=input_tokens_est,
            output_tokens_est=output_tokens_est,
            input_payload=input_payload,
            output_payload=output_payload,
        )
    )


def record_signal_event(
    *,
    session_id: str,
    signal_type: str,
    score: float,
    health_score: float | None = None,
    state_before: str | None = None,
    state_after: str | None = None,
    metadata: dict[str, _Day12Any] | None = None,
    timestamp_ms: int | None = None,
    db_path: str | _Day12Path | None = None,
) -> int:
    """Convenience helper for recording a signal event."""

    repository = SignalEventRepository(db_path)
    return repository.insert(
        SignalEventCreate(
            session_id=session_id,
            timestamp_ms=timestamp_ms,
            signal_type=signal_type,
            score=score,
            health_score=health_score,
            state_before=state_before,
            state_after=state_after,
            metadata=metadata,
        )
    )


# --- Day 12 storage repositories end ---
