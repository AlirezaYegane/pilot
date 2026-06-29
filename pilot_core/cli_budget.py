"""Budget CLI command for Pilot.

Day 54 exposes the Day 51 budget engine as a CLI command:

    pilot budget

The command can read usage events from:
- a SQLite database
- a JSONL fixture
- an empty fallback report

It is intentionally defensive so broken local state does not crash the CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from pilot_core.budget import (
    DEFAULT_DAILY_BUDGET_TOKENS,
    DEFAULT_PLAN_CAP_TOKENS,
    DEFAULT_PLAN_NAME,
    DEFAULT_USAGE_WARNING_RATIO,
    DEFAULT_WEEKLY_BUDGET_TOKENS,
    BudgetReport,
    budget_report_summary,
    build_budget_report,
)

RawEvent = dict[str, object]


def _safe_int(value: object, *, default: int = 0) -> int:
    """Convert value to int safely."""

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


def _safe_float(value: object, *, default: float = 0.0) -> float:
    """Convert value to float safely."""

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str | bytes | bytearray):
        try:
            return float(value)
        except ValueError:
            return default

    return default


def _as_path(value: str | Path | None) -> Path | None:
    """Return a resolved path when value is set."""

    if value is None or str(value).strip() == "":
        return None

    return Path(os.path.expandvars(os.path.expanduser(str(value))))


def default_budget_db_candidates() -> tuple[Path, ...]:
    """Return likely Pilot SQLite database locations."""

    candidates: list[Path] = []

    env_db = _as_path(os.environ.get("PILOT_DB_PATH"))
    if env_db is not None:
        candidates.append(env_db)

    env_data_dir = _as_path(os.environ.get("PILOT_DATA_DIR"))
    if env_data_dir is not None:
        candidates.append(env_data_dir / "pilot.db")

    home = Path.home()
    candidates.extend(
        [
            Path(".pilot") / "pilot.db",
            home / ".claude" / "plugins" / "pilot" / "data" / "pilot.db",
            home / ".pilot" / "pilot.db",
        ]
    )

    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved not in unique:
            unique.append(resolved)

    return tuple(unique)


def find_existing_budget_db(explicit_db_path: str | Path | None = None) -> Path | None:
    """Find an existing Pilot database path."""

    explicit = _as_path(explicit_db_path)
    if explicit is not None:
        return explicit if explicit.exists() else None

    for candidate in default_budget_db_candidates():
        if candidate.exists():
            return candidate

    return None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Return SQLite column names for a table."""

    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return True when a table exists."""

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_expr(columns: set[str], aliases: Sequence[str], *, default: str) -> str:
    """Return the first matching column expression, or a default literal."""

    for alias in aliases:
        if alias in columns:
            return alias

    return default


def load_budget_events_from_sqlite(
    db_path: Path,
    *,
    limit: int = 1_000,
) -> tuple[RawEvent, ...]:
    """Load budget events from a Pilot SQLite database.

    The loader supports several schema generations by inspecting table columns.
    """

    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1")

    if not db_path.exists():
        return ()

    events: list[RawEvent] = []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        for table_name in ("tool_uses", "turns", "events"):
            if not _table_exists(conn, table_name):
                continue

            columns = _table_columns(conn, table_name)
            timestamp_expr = _column_expr(
                columns,
                ("timestamp_ms", "created_at_ms", "started_at", "ended_at"),
                default="NULL",
            )
            total_expr = _column_expr(
                columns,
                ("total_tokens", "token_count", "tokens", "tokens_spent"),
                default="0",
            )
            input_expr = _column_expr(
                columns,
                ("input_tokens", "input_tokens_est", "prompt_tokens"),
                default="0",
            )
            output_expr = _column_expr(
                columns,
                ("output_tokens", "output_tokens_est", "completion_tokens"),
                default="0",
            )
            cost_expr = _column_expr(
                columns,
                ("cost_usd", "total_cost_usd"),
                default="0.0",
            )
            model_expr = _column_expr(columns, ("model_name", "model"), default="NULL")

            query = f"""
                SELECT
                    {timestamp_expr} AS timestamp_ms,
                    {total_expr} AS total_tokens,
                    {input_expr} AS input_tokens,
                    {output_expr} AS output_tokens,
                    {cost_expr} AS cost_usd,
                    {model_expr} AS model_name
                FROM {table_name}
                ORDER BY COALESCE({timestamp_expr}, 0) DESC
                LIMIT ?
            """

            for row in conn.execute(query, (limit,)).fetchall():
                events.append(
                    {
                        "timestamp_ms": _safe_int(row["timestamp_ms"]),
                        "total_tokens": _safe_int(row["total_tokens"]),
                        "input_tokens": _safe_int(row["input_tokens"]),
                        "output_tokens": _safe_int(row["output_tokens"]),
                        "cost_usd": _safe_float(row["cost_usd"]),
                        "model_name": str(row["model_name"])
                        if row["model_name"] is not None
                        else None,
                        "source": table_name,
                    }
                )
    finally:
        conn.close()

    return tuple(reversed(events[-limit:]))


def load_budget_events_from_jsonl(path: Path) -> tuple[RawEvent, ...]:
    """Load usage records from a JSONL fixture file."""

    events: list[RawEvent] = []

    if not path.exists():
        return ()

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "":
            continue

        raw = json.loads(stripped)
        if isinstance(raw, dict):
            events.append(dict(raw))

    return tuple(events)


def _resolve_current_used_tokens(
    events: Sequence[Mapping[str, object]],
    explicit_value: int | None,
) -> int | None:
    """Resolve current used tokens from CLI or event payloads."""

    if explicit_value is not None:
        return max(0, explicit_value)

    values = [
        _safe_int(event.get("current_used_tokens"))
        for event in events
        if "current_used_tokens" in event
    ]

    if values:
        return max(values)

    return None


def build_budget_cli_report(
    *,
    events: Sequence[Mapping[str, object]],
    plan_name: str = DEFAULT_PLAN_NAME,
    plan_cap_tokens: int = DEFAULT_PLAN_CAP_TOKENS,
    current_used_tokens: int | None = None,
    daily_budget_tokens: int = DEFAULT_DAILY_BUDGET_TOKENS,
    weekly_budget_tokens: int = DEFAULT_WEEKLY_BUDGET_TOKENS,
    timezone_offset_minutes: int = 0,
    warning_ratio: float = DEFAULT_USAGE_WARNING_RATIO,
) -> BudgetReport:
    """Build a budget report for CLI display."""

    resolved_current_used_tokens = _resolve_current_used_tokens(events, current_used_tokens)

    return build_budget_report(
        events,
        plan_name=plan_name,
        plan_cap_tokens=plan_cap_tokens,
        current_used_tokens=resolved_current_used_tokens,
        daily_budget_tokens=daily_budget_tokens,
        weekly_budget_tokens=weekly_budget_tokens,
        timezone_offset_minutes=timezone_offset_minutes,
        warning_ratio=warning_ratio,
    )


def _format_tokens(value: object) -> str:
    """Format token values for CLI output."""

    tokens = _safe_int(value)
    return f"{tokens:,}"


def _format_ratio(value: object) -> str:
    """Format ratio values for CLI output."""

    return f"{_safe_float(value) * 100:.1f}%"


def render_budget_text(report: BudgetReport, *, db_path: Path | None = None) -> str:
    """Render a readable budget report."""

    summary = budget_report_summary(report)
    daily = summary["daily"]
    weekly = summary["weekly"]
    eta = summary["eta"]

    if not isinstance(daily, dict) or not isinstance(weekly, dict) or not isinstance(eta, dict):
        raise TypeError("Invalid budget report summary shape")

    lines = [
        "Pilot Budget",
        "============",
        f"Source DB: {db_path if db_path is not None else 'not found / fixture / empty'}",
        f"Plan: {summary['plan_name']}",
        f"Plan cap: {_format_tokens(summary['plan_cap_tokens'])} tokens",
        f"Current used: {_format_tokens(summary['current_used_tokens'])} tokens",
        "",
        "Daily",
        "-----",
        f"Tokens: {_format_tokens(daily['total_tokens'])} / {_format_tokens(daily['budget_tokens'])}",
        f"Usage: {_format_ratio(daily['usage_ratio'])}",
        f"Warn: {daily['should_warn']}",
        "",
        "Weekly",
        "------",
        f"Tokens: {_format_tokens(weekly['total_tokens'])} / {_format_tokens(weekly['budget_tokens'])}",
        f"Usage: {_format_ratio(weekly['usage_ratio'])}",
        f"Warn: {weekly['should_warn']}",
        "",
        "ETA",
        "---",
        f"Remaining: {_format_tokens(eta['remaining_tokens'])} tokens",
        f"Rate: {eta['recent_rate_tokens_per_minute']} tokens/min",
        f"ETA minutes: {eta['eta_minutes']}",
        f"Rate-limit fired: {summary['rate_limit_fired']}",
        "",
        f"Overall warning: {summary['should_warn']}",
    ]

    return "\n".join(lines)


def build_budget_arg_parser() -> argparse.ArgumentParser:
    """Build parser for pilot budget."""

    parser = argparse.ArgumentParser(prog="pilot budget")
    parser.add_argument("--db", default=None, help="Path to Pilot SQLite DB")
    parser.add_argument("--fixture", default=None, help="Read usage events from JSONL fixture")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    parser.add_argument("--limit", type=int, default=1_000, help="Max DB rows per table")
    parser.add_argument("--plan-name", default=DEFAULT_PLAN_NAME)
    parser.add_argument("--plan-cap-tokens", type=int, default=DEFAULT_PLAN_CAP_TOKENS)
    parser.add_argument("--current-used-tokens", type=int, default=None)
    parser.add_argument("--daily-budget-tokens", type=int, default=DEFAULT_DAILY_BUDGET_TOKENS)
    parser.add_argument("--weekly-budget-tokens", type=int, default=DEFAULT_WEEKLY_BUDGET_TOKENS)
    parser.add_argument("--timezone-offset-minutes", type=int, default=0)
    parser.add_argument("--warning-ratio", type=float, default=DEFAULT_USAGE_WARNING_RATIO)
    return parser


def budget_main(argv: Sequence[str] | None = None) -> int:
    """Run pilot budget."""

    parser = build_budget_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    db_path: Path | None = None

    if args.fixture is not None:
        events = load_budget_events_from_jsonl(Path(args.fixture))
    else:
        db_path = find_existing_budget_db(args.db)
        events = load_budget_events_from_sqlite(db_path, limit=args.limit) if db_path else ()

    report = build_budget_cli_report(
        events=events,
        plan_name=str(args.plan_name),
        plan_cap_tokens=int(args.plan_cap_tokens),
        current_used_tokens=args.current_used_tokens,
        daily_budget_tokens=int(args.daily_budget_tokens),
        weekly_budget_tokens=int(args.weekly_budget_tokens),
        timezone_offset_minutes=int(args.timezone_offset_minutes),
        warning_ratio=float(args.warning_ratio),
    )

    if bool(args.json):
        print(json.dumps(budget_report_summary(report), indent=2, sort_keys=True))
    else:
        print(render_budget_text(report, db_path=db_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(budget_main(sys.argv[1:]))
