from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pilot_core.cli_budget import (
    build_budget_cli_report,
    load_budget_events_from_jsonl,
    load_budget_events_from_sqlite,
    render_budget_text,
)
from pilot_core.cli_diagnostics import (
    diagnostic_report_summary,
    run_db_diagnostics,
    run_doctor,
)


def test_load_budget_events_from_jsonl(tmp_path: Path) -> None:
    fixture = tmp_path / "usage.jsonl"
    fixture.write_text(
        "\n".join(
            [
                json.dumps({"total_tokens": 100, "timestamp_ms": 0}),
                json.dumps({"input_tokens": 20, "output_tokens": 30, "timestamp_ms": 60_000}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    events = load_budget_events_from_jsonl(fixture)

    assert len(events) == 2
    assert events[0]["total_tokens"] == 100
    assert events[1]["input_tokens"] == 20


def test_load_budget_events_from_sqlite_supports_tool_uses_table(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE tool_uses (
                id TEXT PRIMARY KEY,
                timestamp_ms INTEGER,
                total_tokens INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cost_usd REAL,
                model_name TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tool_uses (
                id, timestamp_ms, total_tokens, input_tokens, output_tokens, cost_usd, model_name
            )
            VALUES ('tool-1', 1000, 300, 100, 200, 0.01, 'test-model')
            """
        )
        conn.commit()
    finally:
        conn.close()

    events = load_budget_events_from_sqlite(db_path)

    assert len(events) == 1
    assert events[0]["total_tokens"] == 300
    assert events[0]["source"] == "tool_uses"


def test_build_budget_cli_report_and_render_text() -> None:
    report = build_budget_cli_report(
        events=(
            {"total_tokens": 50_000, "timestamp_ms": 0, "current_used_tokens": 249_600_000},
            {"total_tokens": 50_000, "timestamp_ms": 60_000, "current_used_tokens": 249_600_000},
            {"total_tokens": 50_000, "timestamp_ms": 120_000, "current_used_tokens": 249_600_000},
        ),
        plan_cap_tokens=250_000_000,
        daily_budget_tokens=100_000,
        current_used_tokens=None,
        timezone_offset_minutes=0,
    )

    text = render_budget_text(report)

    assert "Pilot Budget" in text
    assert report.daily.should_warn is True
    assert report.current_used_tokens == 249_600_000


def test_db_diagnostics_warns_when_db_missing(tmp_path: Path) -> None:
    checks = run_db_diagnostics(tmp_path / "missing.db")

    assert checks
    assert checks[0].status == "WARN"


def test_doctor_summary_is_serialisable(tmp_path: Path) -> None:
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / "hooks").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (tmp_path / "hooks" / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='pilot-cc'\n", encoding="utf-8")

    report = run_doctor(project_root=tmp_path, db_path=None)
    summary = diagnostic_report_summary(report)

    assert isinstance(summary["checks"], list)
    assert summary["status"] in {"OK", "WARN", "FAIL"}
