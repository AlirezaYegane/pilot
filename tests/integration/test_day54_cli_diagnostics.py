from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pilot_core.cli_budget import build_budget_cli_report, load_budget_events_from_sqlite
from pilot_core.cli_diagnostics import diagnostic_report_summary, run_doctor


def make_project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()

    (root / "pyproject.toml").write_text("[project]\nname='pilot-cc'\n", encoding="utf-8")

    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "pilot", "version": "0.1.0"}),
        encoding="utf-8",
    )

    hooks_dir = root / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "python hooks/stop.py"}]}]
                }
            }
        ),
        encoding="utf-8",
    )

    for filename in (
        "session_start.py",
        "user_prompt_submit.py",
        "pre_tool_use.py",
        "post_tool_use.py",
        "post_tool_failure.py",
        "stop.py",
        "session_end.py",
    ):
        (hooks_dir / filename).write_text(
            "from __future__ import annotations\n\nraise SystemExit(0)\n",
            encoding="utf-8",
        )

    return root


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "pilot.db"
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


def test_day54_doctor_and_budget_integration(tmp_path: Path) -> None:
    project_root = make_project_root(tmp_path)
    db_path = make_db(tmp_path)

    doctor_report = run_doctor(project_root=project_root, db_path=db_path)
    doctor_summary = diagnostic_report_summary(doctor_report)

    assert doctor_summary["failed_count"] == 0

    events = load_budget_events_from_sqlite(db_path)
    budget_report = build_budget_cli_report(
        events=events,
        plan_cap_tokens=250_000_000,
        daily_budget_tokens=100_000,
        current_used_tokens=249_600_000,
    )

    assert len(events) == 5
    assert budget_report.daily.should_warn is True
    assert budget_report.rate_limit_fired is True
