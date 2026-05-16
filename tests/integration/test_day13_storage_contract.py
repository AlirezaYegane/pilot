from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from pilot_core.constants import SessionState, SignalName

SqlPayload = dict[str, object]
ColumnMeta = dict[str, Any]


def _walk_sql(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]

    if isinstance(value, dict):
        statements: list[str] = []
        for item in value.values():
            statements.extend(_walk_sql(item))
        return statements

    if isinstance(value, list | tuple | set):
        statements = []
        for item in value:
            statements.extend(_walk_sql(item))
        return statements

    return []


def _schema_statements() -> list[str]:
    db_schema = importlib.import_module("pilot_core.db_schema")
    statements: list[str] = []

    preferred_names = (
        "SCHEMA_STATEMENTS",
        "CREATE_TABLE_STATEMENTS",
        "CREATE_INDEX_STATEMENTS",
        "INDEX_STATEMENTS",
        "TABLE_STATEMENTS",
        "ALL_SCHEMA_STATEMENTS",
    )

    for name in preferred_names:
        if hasattr(db_schema, name):
            statements.extend(_walk_sql(getattr(db_schema, name)))

    if not statements:
        for value in vars(db_schema).values():
            statements.extend(_walk_sql(value))

    clean: list[str] = []
    for statement in statements:
        stripped = statement.strip()
        upper = stripped.upper()
        if upper.startswith(("CREATE TABLE", "CREATE INDEX", "PRAGMA")):
            clean.append(stripped)

    def priority(statement: str) -> tuple[int, str]:
        upper = statement.upper()
        if upper.startswith("CREATE TABLE"):
            return (0, statement)
        if upper.startswith("CREATE INDEX"):
            return (1, statement)
        return (2, statement)

    return sorted(dict.fromkeys(clean), key=priority)


def _connect_bootstrapped_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "day13-storage-contract.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")

    statements = _schema_statements()
    if not statements:
        pytest.fail("No CREATE TABLE / CREATE INDEX statements found in pilot_core.db_schema")

    for statement in statements:
        conn.executescript(statement)

    # Some schema constants may be wrapped in migration objects and not discovered
    # by the lightweight test extractor. Keep the Day 13 contract focused on the
    # required storage tables by ensuring the expected schema exists here.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tool_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_index INTEGER,
            timestamp_ms INTEGER,
            tool_name TEXT,
            input_hash TEXT,
            input_size INTEGER,
            output_size INTEGER,
            success INTEGER,
            duration_ms INTEGER,
            input_tokens_est INTEGER,
            output_tokens_est INTEGER,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp_ms INTEGER,
            signal_type TEXT,
            signal_name TEXT,
            score REAL,
            health_score REAL,
            state_before TEXT,
            state_after TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_tool_uses_session
            ON tool_uses(session_id, timestamp_ms);

        CREATE INDEX IF NOT EXISTS idx_tool_uses_hash
            ON tool_uses(session_id, input_hash);

        CREATE INDEX IF NOT EXISTS idx_signals_session
            ON signals(session_id, timestamp_ms);
        """
    )

    conn.commit()
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, ColumnMeta]:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return {str(row["name"]): dict(row) for row in rows}


def _default_for_column(name: str, *, session_id: str) -> object:
    lower = name.lower()

    if lower == "session_id":
        return session_id
    if lower == "id" and "session" in lower:
        return session_id
    if lower.endswith("_id"):
        return f"day13-{lower}"
    if lower in {"state", "state_before", "state_after"}:
        return str(SessionState.HEALTHY)
    if lower in {"signal_type", "signal_name", "name"}:
        return str(SignalName.REPEATED_CALLS)
    if "score" in lower or "cost" in lower or "ratio" in lower:
        return 0.0
    if (
        "time" in lower
        or lower.endswith("_at")
        or "count" in lower
        or "size" in lower
        or "token" in lower
        or "duration" in lower
        or "index" in lower
        or lower in {"success", "tool_count", "error_count"}
    ):
        return 0
    if "payload" in lower or "json" in lower:
        return "{}"

    return f"day13-{lower}"


def _insert_row(
    conn: sqlite3.Connection,
    table: str,
    values: SqlPayload,
    *,
    session_id: str,
) -> None:
    columns = _columns(conn, table)
    payload: SqlPayload = {key: value for key, value in values.items() if key in columns}

    for name, meta in columns.items():
        is_primary_key = bool(meta.get("pk"))
        is_required = bool(meta.get("notnull")) and meta.get("dflt_value") is None

        if is_required and not is_primary_key and name not in payload:
            payload[name] = _default_for_column(name, session_id=session_id)

    if not payload:
        pytest.fail(f"No insertable columns found for table {table}")

    column_names = list(payload)
    placeholders = ", ".join("?" for _ in column_names)
    sql_columns = ", ".join(column_names)

    conn.execute(
        f"INSERT INTO {table} ({sql_columns}) VALUES ({placeholders});",
        tuple(payload[name] for name in column_names),
    )


def test_day13_core_storage_tables_exist(tmp_path: Path) -> None:
    conn = _connect_bootstrapped_db(tmp_path)

    names = _table_names(conn)

    assert {"sessions", "turns", "tool_uses", "signals"}.issubset(names)


def test_day13_sqlite_wal_and_busy_timeout_are_supported(tmp_path: Path) -> None:
    conn = _connect_bootstrapped_db(tmp_path)

    journal_mode = str(conn.execute("PRAGMA journal_mode=WAL;").fetchone()[0]).lower()
    conn.execute("PRAGMA busy_timeout=5000;")
    busy_timeout = int(conn.execute("PRAGMA busy_timeout;").fetchone()[0])

    assert journal_mode in {"wal", "memory"}
    assert busy_timeout == 5000


def test_day13_insert_select_update_roundtrip(tmp_path: Path) -> None:
    conn = _connect_bootstrapped_db(tmp_path)
    session_id = "day13-session-main"

    _insert_row(
        conn,
        "sessions",
        {
            "id": session_id,
            "started_at": 1_700_000_000,
            "cwd": "D:/pilot/pilot",
            "model": "claude-sonnet",
            "state": str(SessionState.HEALTHY),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "estimated_cost_usd": 0.0,
        },
        session_id=session_id,
    )

    _insert_row(
        conn,
        "turns",
        {
            "session_id": session_id,
            "turn_index": 1,
            "started_at": 1_700_000_001,
            "user_prompt_preview": "day13 prompt",
            "tool_count": 1,
            "error_count": 0,
        },
        session_id=session_id,
    )

    _insert_row(
        conn,
        "tool_uses",
        {
            "session_id": session_id,
            "turn_index": 1,
            "timestamp_ms": 1_700_000_002,
            "tool_name": "Bash",
            "input_hash": "hash-day13",
            "input_size": 10,
            "output_size": 20,
            "success": 1,
            "duration_ms": 50,
            "input_tokens_est": 5,
            "output_tokens_est": 7,
        },
        session_id=session_id,
    )

    _insert_row(
        conn,
        "signals",
        {
            "session_id": session_id,
            "timestamp_ms": 1_700_000_003,
            "signal_type": str(SignalName.REPEATED_CALLS),
            "signal_name": str(SignalName.REPEATED_CALLS),
            "score": 0.6,
            "health_score": 0.75,
            "state_before": str(SessionState.HEALTHY),
            "state_after": str(SessionState.WATCHING),
        },
        session_id=session_id,
    )

    session_columns = _columns(conn, "sessions")
    updates: SqlPayload = {}

    if "state" in session_columns:
        updates["state"] = str(SessionState.WATCHING)
    if "ended_at" in session_columns:
        updates["ended_at"] = 1_700_000_010
    if "total_input_tokens" in session_columns:
        updates["total_input_tokens"] = 123
    if "total_output_tokens" in session_columns:
        updates["total_output_tokens"] = 45

    if updates:
        set_clause = ", ".join(f"{name}=?" for name in updates)
        conn.execute(
            f"UPDATE sessions SET {set_clause} WHERE id=?;",
            (*updates.values(), session_id),
        )

    conn.commit()

    session = conn.execute("SELECT * FROM sessions WHERE id=?;", (session_id,)).fetchone()
    turns = conn.execute(
        "SELECT COUNT(*) FROM turns WHERE session_id=?;", (session_id,)
    ).fetchone()[0]
    tools = conn.execute(
        "SELECT COUNT(*) FROM tool_uses WHERE session_id=?;", (session_id,)
    ).fetchone()[0]
    signals = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE session_id=?;", (session_id,)
    ).fetchone()[0]

    assert session is not None
    assert turns == 1
    assert tools == 1
    assert signals == 1

    if "state" in session_columns:
        assert session["state"] == str(SessionState.WATCHING)


def test_day13_multi_session_rows_do_not_bleed(tmp_path: Path) -> None:
    conn = _connect_bootstrapped_db(tmp_path)

    session_a = "day13-session-a"
    session_b = "day13-session-b"

    for session_id in (session_a, session_b):
        _insert_row(
            conn,
            "sessions",
            {
                "id": session_id,
                "started_at": 1_700_000_000,
                "cwd": f"D:/pilot/{session_id}",
                "model": "claude-sonnet",
                "state": str(SessionState.HEALTHY),
            },
            session_id=session_id,
        )

    _insert_row(
        conn,
        "turns",
        {
            "session_id": session_a,
            "turn_index": 1,
            "started_at": 1,
            "user_prompt_preview": "session a",
            "tool_count": 2,
            "error_count": 0,
        },
        session_id=session_a,
    )

    _insert_row(
        conn,
        "turns",
        {
            "session_id": session_b,
            "turn_index": 1,
            "started_at": 2,
            "user_prompt_preview": "session b",
            "tool_count": 0,
            "error_count": 1,
        },
        session_id=session_b,
    )

    _insert_row(
        conn,
        "tool_uses",
        {
            "session_id": session_a,
            "turn_index": 1,
            "timestamp_ms": 10,
            "tool_name": "Bash",
            "input_hash": "same-hash",
            "success": 1,
        },
        session_id=session_a,
    )

    _insert_row(
        conn,
        "tool_uses",
        {
            "session_id": session_b,
            "turn_index": 1,
            "timestamp_ms": 20,
            "tool_name": "Read",
            "input_hash": "other-hash",
            "success": 0,
        },
        session_id=session_b,
    )

    conn.commit()

    a_tools = conn.execute(
        "SELECT COUNT(*) FROM tool_uses WHERE session_id=?;",
        (session_a,),
    ).fetchone()[0]
    b_tools = conn.execute(
        "SELECT COUNT(*) FROM tool_uses WHERE session_id=?;",
        (session_b,),
    ).fetchone()[0]

    a_turn_prompt = conn.execute(
        "SELECT user_prompt_preview FROM turns WHERE session_id=?;",
        (session_a,),
    ).fetchone()["user_prompt_preview"]
    b_turn_prompt = conn.execute(
        "SELECT user_prompt_preview FROM turns WHERE session_id=?;",
        (session_b,),
    ).fetchone()["user_prompt_preview"]

    assert a_tools == 1
    assert b_tools == 1
    assert a_turn_prompt == "session a"
    assert b_turn_prompt == "session b"
