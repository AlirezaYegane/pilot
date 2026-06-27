from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from pilot_core.budget import budget_report_summary, build_budget_report

RawRecord = Mapping[str, object]
FIXTURE_DIR = Path("tests") / "fixtures" / "replay_cases"


def read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        assert isinstance(raw, dict)
        records.append(cast(dict[str, object], raw))

    return records


def case_int(records: Sequence[RawRecord], key: str, default: int) -> int:
    values: list[int] = []

    for record in records:
        value = record.get(key)
        if isinstance(value, int):
            values.append(value)

    return max(values) if values else default


def test_day51_replay_cases_have_budget_reports() -> None:
    expected_cases = {
        "healthy_session.jsonl",
        "degraded_session.jsonl",
        "noisy_session.jsonl",
        "ambiguous_session.jsonl",
    }

    actual_cases = {path.name for path in FIXTURE_DIR.glob("*.jsonl")}

    assert expected_cases <= actual_cases

    for filename in sorted(expected_cases):
        records = read_jsonl(FIXTURE_DIR / filename)
        now_ms = case_int(records, "timestamp_ms", 0)
        current_used_tokens = case_int(records, "current_used_tokens", 0)

        report = build_budget_report(
            records,
            now_ms=now_ms,
            current_used_tokens=current_used_tokens,
            plan_cap_tokens=250_000_000,
            daily_budget_tokens=5_000_000,
            weekly_budget_tokens=30_000_000,
        )

        assert report.daily.total_tokens >= 0
        assert report.weekly.total_tokens >= report.daily.total_tokens
        assert report.eta.remaining_tokens >= 0
        assert report.explanation.strip()

        summary = budget_report_summary(report)
        assert summary["plan_name"] == "max5"
        assert isinstance(summary["eta"], dict)


def test_day51_degraded_session_integrates_rate_limit_pressure() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    now_ms = case_int(records, "timestamp_ms", 0)
    current_used_tokens = case_int(records, "current_used_tokens", 0)

    report = build_budget_report(
        records,
        now_ms=now_ms,
        current_used_tokens=current_used_tokens,
        plan_cap_tokens=250_000_000,
        daily_budget_tokens=1_000_000,
        weekly_budget_tokens=5_000_000,
    )

    assert report.rate_limit_fired is True
    assert report.eta.fired is True
    assert report.rate_limit_score >= 0.85
    assert report.should_warn is True


def test_day51_healthy_session_does_not_emit_budget_warning() -> None:
    records = read_jsonl(FIXTURE_DIR / "healthy_session.jsonl")
    now_ms = case_int(records, "timestamp_ms", 0)
    current_used_tokens = case_int(records, "current_used_tokens", 0)

    report = build_budget_report(
        records,
        now_ms=now_ms,
        current_used_tokens=current_used_tokens,
        plan_cap_tokens=250_000_000,
        daily_budget_tokens=5_000_000,
        weekly_budget_tokens=30_000_000,
    )

    assert report.daily.should_warn is False
    assert report.weekly.should_warn is False
    assert report.rate_limit_fired is False
