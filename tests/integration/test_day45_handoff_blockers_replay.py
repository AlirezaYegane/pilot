from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from pilot_core.handoff_blockers import extract_handoff_blockers

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


def test_day45_replay_fixtures_exist() -> None:
    expected = {
        "healthy_session.jsonl",
        "noisy_session.jsonl",
        "ambiguous_session.jsonl",
        "degraded_session.jsonl",
    }

    actual = {path.name for path in FIXTURE_DIR.glob("*.jsonl")}

    assert expected <= actual


def test_day45_healthy_session_has_no_handoff_blockers() -> None:
    records = read_jsonl(FIXTURE_DIR / "healthy_session.jsonl")

    result = extract_handoff_blockers(records)

    assert result.blockers == tuple()
    assert result.do_not_redo == tuple()
    assert result.failed_event_count == 0


def test_day45_degraded_session_extracts_blockers_and_do_not_redo() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")

    result = extract_handoff_blockers(records)

    assert result.has_blockers
    assert result.has_do_not_redo_items
    assert result.failed_event_count >= 3
    assert result.failing_loops or result.repeated_attempts
    assert any("retry" in item.item.lower() for item in result.do_not_redo)


def test_day45_noisy_session_does_not_create_strong_false_positive() -> None:
    records = read_jsonl(FIXTURE_DIR / "noisy_session.jsonl")

    result = extract_handoff_blockers(records)

    assert len(result.blockers) <= 1
    assert len(result.do_not_redo) <= 1


def test_day45_ambiguous_session_is_bounded() -> None:
    records = read_jsonl(FIXTURE_DIR / "ambiguous_session.jsonl")

    result = extract_handoff_blockers(records)

    assert result.observed_event_count > 0
    assert len(result.blockers) <= 2
    assert len(result.do_not_redo) <= 2
