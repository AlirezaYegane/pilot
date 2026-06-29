"""Session CLI helpers for Pilot.

Day 53 adds:
- pilot sessions
- pilot show <session_id>

The module reads the local SQLite database defensively and renders session
list/detail views. It is schema-tolerant so older development databases do not
crash the CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import TextIO

from pilot_core.paths import default_data_dir
from pilot_core.render.session_view import (
    SessionDetail,
    SessionListItem,
    normalise_session_detail,
    normalise_session_list_item,
    render_session_detail,
    render_session_list,
    session_detail_summary,
    session_list_summary,
)

DEFAULT_DB_FILENAME = "pilot.db"


def resolve_db_path(raw_path: str | Path | None = None) -> Path:
    """Resolve the SQLite DB path used by session CLI commands."""

    if raw_path is not None:
        return Path(raw_path).expanduser()

    env_path = os.environ.get("PILOT_DB_PATH") or os.environ.get("PILOT_DB")
    if env_path:
        return Path(env_path).expanduser()

    return default_data_dir() / DEFAULT_DB_FILENAME


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with row objects."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    """Return all table names."""

    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row["name"]) for row in rows}


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return True when a table exists."""

    return table_name in _table_names(conn)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Return column names for a table."""

    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _first_existing(columns: set[str], candidates: Sequence[str]) -> str | None:
    """Return first candidate present in columns."""

    for candidate in candidates:
        if candidate in columns:
            return candidate

    return None


def _safe_int(value: object, *, default: int = 0) -> int:
    """Convert a loose SQLite/object value to int safely."""

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


def _row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    """Convert sqlite row to dict."""

    keys = tuple(row.keys())
    return {key: row[key] for key in keys}


def _count_by_session(
    conn: sqlite3.Connection,
    *,
    table_name: str,
) -> dict[str, int]:
    """Count records grouped by session id."""

    if not _table_exists(conn, table_name):
        return {}

    columns = _table_columns(conn, table_name)
    session_col = _first_existing(columns, ("session_id", "session", "id"))
    if session_col is None:
        return {}

    rows = conn.execute(
        f"SELECT {session_col} AS session_id, COUNT(*) AS count "
        f"FROM {table_name} GROUP BY {session_col}"
    ).fetchall()

    return {str(row["session_id"]): int(row["count"]) for row in rows}


def _token_sum_by_session(
    conn: sqlite3.Connection,
    *,
    table_name: str,
) -> dict[str, int]:
    """Sum total tokens grouped by session id."""

    if not _table_exists(conn, table_name):
        return {}

    columns = _table_columns(conn, table_name)
    session_col = _first_existing(columns, ("session_id", "session", "id"))
    token_col = _first_existing(
        columns,
        ("total_tokens", "tokens", "estimated_tokens", "token_count"),
    )

    if session_col is None or token_col is None:
        return {}

    rows = conn.execute(
        f"SELECT {session_col} AS session_id, SUM({token_col}) AS total_tokens "
        f"FROM {table_name} GROUP BY {session_col}"
    ).fetchall()

    return {str(row["session_id"]): int(row["total_tokens"] or 0) for row in rows}


def _session_table(conn: sqlite3.Connection) -> str | None:
    """Return the sessions table name if present."""

    tables = _table_names(conn)
    for candidate in ("sessions", "session"):
        if candidate in tables:
            return candidate

    return None


def _tool_table(conn: sqlite3.Connection) -> str | None:
    """Return the tool-use table name if present."""

    tables = _table_names(conn)
    for candidate in ("tool_uses", "tool_calls", "tools"):
        if candidate in tables:
            return candidate

    return None


def _signal_table(conn: sqlite3.Connection) -> str | None:
    """Return the signals table name if present."""

    tables = _table_names(conn)
    for candidate in ("signals", "signal_results", "session_signals"):
        if candidate in tables:
            return candidate

    return None


def load_session_list_from_db(
    db_path: str | Path,
    *,
    limit: int = 20,
) -> tuple[SessionListItem, ...]:
    """Load recent sessions from SQLite."""

    path = Path(db_path)
    if not path.exists():
        return tuple()

    with closing(_connect(path)) as conn:
        table = _session_table(conn)
        if table is None:
            return tuple()

        columns = _table_columns(conn, table)
        session_col = _first_existing(columns, ("id", "session_id"))
        if session_col is None:
            return tuple()

        tool_table = _tool_table(conn)
        signal_table = _signal_table(conn)

        tool_counts = (
            _count_by_session(conn, table_name=tool_table) if tool_table is not None else {}
        )
        signal_counts = (
            _count_by_session(conn, table_name=signal_table) if signal_table is not None else {}
        )
        token_sums = (
            _token_sum_by_session(conn, table_name=tool_table) if tool_table is not None else {}
        )

        order_col = _first_existing(
            columns,
            (
                "updated_at_ms",
                "updated_at",
                "ended_at_ms",
                "ended_at",
                "started_at_ms",
                "started_at",
            ),
        )

        select_cols = ", ".join(sorted(columns))
        order_sql = f" ORDER BY {order_col} DESC" if order_col is not None else ""
        sql = f"SELECT {select_cols} FROM {table}{order_sql} LIMIT ?"

        rows = conn.execute(sql, (max(1, limit),)).fetchall()

        items: list[SessionListItem] = []
        for row in rows:
            raw = _row_to_dict(row)
            session_id = str(raw.get(session_col, ""))

            raw["session_id"] = session_id
            raw["tool_call_count"] = _safe_int(
                raw.get("tool_call_count", tool_counts.get(session_id, 0))
            )
            raw["signal_count"] = _safe_int(
                raw.get("signal_count", signal_counts.get(session_id, 0))
            )
            raw["total_tokens"] = _safe_int(raw.get("total_tokens", token_sums.get(session_id, 0)))

            items.append(normalise_session_list_item(_session_kwargs(raw)))

        return tuple(items)


def _session_kwargs(raw: dict[str, object]) -> dict[str, object]:
    """Map loose DB columns into SessionListItem kwargs."""

    return {
        "session_id": raw.get("session_id", raw.get("id", "unknown-session")),
        "state": raw.get("state", "healthy"),
        "health_score": raw.get("health_score", raw.get("health")),
        "started_at_ms": raw.get("started_at_ms", raw.get("started_at")),
        "ended_at_ms": raw.get("ended_at_ms", raw.get("ended_at")),
        "updated_at_ms": raw.get("updated_at_ms", raw.get("updated_at")),
        "tool_call_count": raw.get("tool_call_count", 0),
        "signal_count": raw.get("signal_count", 0),
        "total_tokens": raw.get("total_tokens", 0),
        "handoff_summary_path": raw.get("handoff_summary_path"),
    }


def _query_rows_for_session(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    session_id: str,
    max_rows: int,
) -> list[dict[str, object]]:
    """Query rows for one session from a schema-tolerant table."""

    if not _table_exists(conn, table_name):
        return []

    columns = _table_columns(conn, table_name)
    session_col = _first_existing(columns, ("session_id", "session"))
    if session_col is None:
        return []

    order_col = _first_existing(
        columns,
        ("timestamp_ms", "created_at_ms", "created_at", "started_at_ms", "started_at"),
    )

    select_cols = ", ".join(sorted(columns))
    order_sql = f" ORDER BY {order_col} DESC" if order_col is not None else ""
    sql = f"SELECT {select_cols} FROM {table_name} WHERE {session_col} = ?{order_sql} LIMIT ?"

    rows = conn.execute(sql, (session_id, max(1, max_rows))).fetchall()
    return [_row_to_dict(row) for row in rows]


def _tool_kwargs(raw: dict[str, object]) -> dict[str, object]:
    """Map loose DB columns into tool renderer kwargs."""

    return {
        "tool_name": raw.get("tool_name", raw.get("name", "unknown")),
        "success": raw.get("success", raw.get("ok", raw.get("error") in (None, ""))),
        "timestamp_ms": raw.get("timestamp_ms", raw.get("created_at")),
        "total_tokens": raw.get("total_tokens", raw.get("tokens", 0)),
        "error_text": raw.get("error_text", raw.get("error", "")),
        "input_hash": raw.get("input_hash", ""),
    }


def _signal_kwargs(raw: dict[str, object]) -> dict[str, object]:
    """Map loose DB columns into signal renderer kwargs."""

    return {
        "signal_name": raw.get("signal_name", raw.get("name", "token_burn")),
        "score": raw.get("score", 0.0),
        "confidence": raw.get("confidence", 1.0),
        "fired": raw.get("fired", False),
        "explanation": raw.get("explanation", ""),
        "timestamp_ms": raw.get("timestamp_ms", raw.get("created_at")),
    }


def load_session_detail_from_db(
    db_path: str | Path,
    session_id: str,
    *,
    max_rows: int = 20,
) -> SessionDetail | None:
    """Load one session detail from SQLite."""

    path = Path(db_path)
    if not path.exists():
        return None

    with closing(_connect(path)) as conn:
        table = _session_table(conn)
        if table is None:
            return None

        columns = _table_columns(conn, table)
        session_col = _first_existing(columns, ("id", "session_id"))
        if session_col is None:
            return None

        select_cols = ", ".join(sorted(columns))
        rows = conn.execute(
            f"SELECT {select_cols} FROM {table} WHERE {session_col} = ? LIMIT 1",
            (session_id,),
        ).fetchall()

        if not rows:
            return None

        raw_session = _row_to_dict(rows[0])
        raw_session["session_id"] = session_id

        tool_table = _tool_table(conn)
        signal_table = _signal_table(conn)

        tool_rows = (
            _query_rows_for_session(
                conn,
                table_name=tool_table,
                session_id=session_id,
                max_rows=max_rows,
            )
            if tool_table is not None
            else []
        )
        signal_rows = (
            _query_rows_for_session(
                conn,
                table_name=signal_table,
                session_id=session_id,
                max_rows=max_rows,
            )
            if signal_table is not None
            else []
        )

        raw_session["tool_call_count"] = len(tool_rows)
        raw_session["signal_count"] = len(signal_rows)
        raw_session["total_tokens"] = sum(
            _safe_int(row.get("total_tokens", row.get("tokens", 0))) for row in tool_rows
        )

        return normalise_session_detail(
            _session_kwargs(raw_session),
            signals=tuple(_signal_kwargs(row) for row in signal_rows),
            tools=tuple(_tool_kwargs(row) for row in tool_rows),
            handoff_path=str(raw_session.get("handoff_summary_path") or "") or None,
        )


def _session_to_dict(item: SessionListItem) -> dict[str, object]:
    """Return serialisable session item."""

    return {
        "session_id": item.session_id,
        "state": item.state.value,
        "health_score": item.health_score,
        "started_at_ms": item.started_at_ms,
        "ended_at_ms": item.ended_at_ms,
        "updated_at_ms": item.updated_at_ms,
        "tool_call_count": item.tool_call_count,
        "signal_count": item.signal_count,
        "total_tokens": item.total_tokens,
        "handoff_summary_path": item.handoff_summary_path,
    }


def run_sessions_command(
    *,
    db_path: str | Path,
    limit: int = 20,
    as_json: bool = False,
    out: TextIO = sys.stdout,
) -> int:
    """Run the sessions command."""

    sessions = load_session_list_from_db(db_path, limit=limit)

    if as_json:
        payload = {
            "summary": session_list_summary(sessions),
            "sessions": [_session_to_dict(item) for item in sessions],
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=out)
        return 0

    print(render_session_list(sessions, limit=limit), file=out)
    return 0


def run_show_command(
    *,
    db_path: str | Path,
    session_id: str,
    as_json: bool = False,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    """Run the show command."""

    detail = load_session_detail_from_db(db_path, session_id)

    if detail is None:
        message = f"Pilot session not found: {session_id}"
        if as_json:
            print(json.dumps({"error": message}, indent=2), file=out)
        else:
            print(message, file=err)
        return 1

    if as_json:
        payload = {
            "summary": session_detail_summary(detail),
            "session": _session_to_dict(detail.session),
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=out)
        return 0

    print(render_session_detail(detail), file=out)
    return 0


def session_cli_main(argv: Sequence[str] | None = None) -> int:
    """Run Day 53 session CLI commands."""

    parser = argparse.ArgumentParser(prog="pilot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sessions_parser = subparsers.add_parser("sessions", help="List Pilot sessions")
    sessions_parser.add_argument("--db", default=None, help="Path to Pilot SQLite database")
    sessions_parser.add_argument("--limit", type=int, default=20, help="Maximum sessions to show")
    sessions_parser.add_argument("--json", action="store_true", help="Emit JSON")

    show_parser = subparsers.add_parser("show", help="Show one Pilot session")
    show_parser.add_argument("session_id", help="Session id to show")
    show_parser.add_argument("--db", default=None, help="Path to Pilot SQLite database")
    show_parser.add_argument("--json", action="store_true", help="Emit JSON")

    args = parser.parse_args(list(argv) if argv is not None else None)
    db_path = resolve_db_path(args.db)

    if args.command == "sessions":
        return run_sessions_command(
            db_path=db_path,
            limit=max(1, int(args.limit)),
            as_json=bool(args.json),
        )

    if args.command == "show":
        return run_show_command(
            db_path=db_path,
            session_id=str(args.session_id),
            as_json=bool(args.json),
        )

    parser.print_help()
    return 2


def maybe_handle_session_cli(argv: Sequence[str] | None = None) -> int | None:
    """Return an exit code when argv belongs to Day 53 commands."""

    args = list(sys.argv[1:] if argv is None else argv)

    if not args:
        return None

    if args[0] not in {"sessions", "show"}:
        return None

    return session_cli_main(args)


def main() -> int:
    """Entry point for running this module directly."""

    return session_cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
