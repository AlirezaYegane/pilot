"""Day 54 smoke test for pilot budget and pilot doctor."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def make_smoke_project(temp_root: Path) -> Path:
    """Create a small plugin-like project root."""

    project_root = temp_root / "pilot-smoke"
    project_root.mkdir()

    (project_root / "pyproject.toml").write_text("[project]\nname='pilot-cc'\n", encoding="utf-8")

    plugin_dir = project_root / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text('{"name": "pilot"}\n', encoding="utf-8")

    hooks_dir = project_root / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")

    hook_body = "from __future__ import annotations\n\nraise SystemExit(0)\n"
    for filename in (
        "session_start.py",
        "user_prompt_submit.py",
        "pre_tool_use.py",
        "post_tool_use.py",
        "post_tool_failure.py",
        "stop.py",
        "session_end.py",
    ):
        (hooks_dir / filename).write_text(hook_body, encoding="utf-8")

    return project_root


def make_smoke_db(temp_root: Path) -> Path:
    """Create a small Pilot-like DB."""

    db_path = temp_root / "pilot.db"
    conn = sqlite3.connect(db_path)

    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, state TEXT)")
        conn.execute(
            "CREATE TABLE turns (id TEXT PRIMARY KEY, timestamp_ms INTEGER, total_tokens INTEGER)"
        )
        conn.execute(
            """
            CREATE TABLE tool_uses (
                id TEXT PRIMARY KEY,
                timestamp_ms INTEGER,
                total_tokens INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                current_used_tokens INTEGER
            )
            """
        )
        conn.execute("CREATE TABLE signals (id TEXT PRIMARY KEY, signal_name TEXT)")

        for index in range(5):
            conn.execute(
                """
                INSERT INTO tool_uses (
                    id, timestamp_ms, total_tokens, input_tokens, output_tokens, current_used_tokens
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"tool-{index}",
                    index * 60_000,
                    50_000,
                    20_000,
                    30_000,
                    249_600_000,
                ),
            )

        conn.commit()
    finally:
        conn.close()

    return db_path


def main() -> int:
    """Run smoke and print JSON summary."""

    from pilot_core.cli_budget import build_budget_cli_report, load_budget_events_from_sqlite
    from pilot_core.cli_diagnostics import diagnostic_report_summary, run_doctor

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        project_root = make_smoke_project(temp_root)
        db_path = make_smoke_db(temp_root)

        doctor = run_doctor(project_root=project_root, db_path=db_path)
        events = load_budget_events_from_sqlite(db_path)
        budget = build_budget_cli_report(
            events=events,
            plan_cap_tokens=250_000_000,
            daily_budget_tokens=100_000,
            current_used_tokens=249_600_000,
        )

        summary = {
            "doctor": diagnostic_report_summary(doctor),
            "budget": {
                "event_count": len(events),
                "daily_should_warn": budget.daily.should_warn,
                "weekly_should_warn": budget.weekly.should_warn,
                "eta_fired": budget.eta.fired,
                "rate_limit_fired": budget.rate_limit_fired,
                "should_warn": budget.should_warn,
            },
        }

        print(json.dumps(summary, indent=2, sort_keys=True))

        return 0 if doctor.failed_count == 0 and budget.should_warn else 1


if __name__ == "__main__":
    raise SystemExit(main())
