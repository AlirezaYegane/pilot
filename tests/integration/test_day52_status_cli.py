from __future__ import annotations

from pathlib import Path

import pytest

from pilot_core.cli import main
from pilot_core.constants import SignalName
from pilot_core.render.status import render_status_snapshot
from pilot_core.status import (
    build_status_snapshot_from_records,
    read_jsonl_records,
    status_snapshot_summary,
)

FIXTURE_DIR = Path("tests") / "fixtures" / "replay_cases"


def test_day52_status_renders_all_replay_cases() -> None:
    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl_records(path)
        snapshot = build_status_snapshot_from_records(records, session_id=path.stem)
        text = render_status_snapshot(snapshot)

        assert "Pilot Status" in text
        assert "Health:" in text
        assert "State:" in text
        assert "Signals:" in text
        assert len(snapshot.signals) == len(SignalName)


def test_day52_healthy_replay_status_is_quiet() -> None:
    records = read_jsonl_records(FIXTURE_DIR / "healthy_session.jsonl")
    snapshot = build_status_snapshot_from_records(records)

    assert snapshot.fired_count == 0
    assert snapshot.health_score >= 0.80


def test_day52_degraded_replay_status_has_signal_pressure() -> None:
    records = read_jsonl_records(FIXTURE_DIR / "degraded_session.jsonl")
    snapshot = build_status_snapshot_from_records(records)
    summary = status_snapshot_summary(snapshot)

    assert snapshot.fired_count >= 5
    assert snapshot.health_score < 0.80
    assert summary["fired_count"] == snapshot.fired_count


def test_day52_cli_status_replay_case_outputs_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["status", "--replay-case", "degraded_session", "--session-id", "cli-test"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Pilot Status" in captured.out
    assert "cli-test" in captured.out
    assert "Signals:" in captured.out


def test_day52_cli_status_json_outputs_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["status", "--replay-case", "healthy_session", "--json"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"health_score"' in captured.out
    assert '"signals"' in captured.out
