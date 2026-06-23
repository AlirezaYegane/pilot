from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from pilot_core.handoff import HandoffFileChange, HandoffFileStatus, HandoffSchema
from pilot_core.handoff_blockers import extract_handoff_blockers
from pilot_core.render.handoff_md import handoff_markdown_summary, render_handoff_markdown

FIXTURE_DIR = Path("tests") / "fixtures" / "replay_cases"


def read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"Expected JSON object in {path}: {line!r}")

        records.append(cast(dict[str, object], raw))

    return records


def build_handoff_for_case(case_name: str, records: list[dict[str, object]]) -> HandoffSchema:
    extraction = extract_handoff_blockers(records)

    return HandoffSchema(
        session_id=f"day46-{case_name}",
        generated_at="2026-06-23T00:00:00+00:00",
        task=f"Replay case: {case_name}",
        progress=(
            f"Rendered handoff markdown from {len(records)} replay records. "
            f"Detected {len(extraction.blockers)} blocker(s)."
        ),
        files_modified=(
            HandoffFileChange(
                path=f"tests/fixtures/replay_cases/{case_name}.jsonl",
                status=HandoffFileStatus.UNKNOWN,
                reason="source replay fixture for markdown rendering test",
                important=False,
            ),
        ),
        blockers=extraction.blockers,
        next_step="Review the rendered handoff and continue from the next concrete step.",
        do_not_redo=extraction.do_not_redo,
        notes=(extraction.explanation,),
    )


def test_day46_all_replay_cases_render_valid_markdown() -> None:
    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        handoff = build_handoff_for_case(path.stem, records)
        markdown = render_handoff_markdown(handoff)
        summary = handoff_markdown_summary(handoff, markdown=markdown)

        assert markdown.startswith("# Pilot Handoff\n")
        assert "## Task" in markdown
        assert "## Progress" in markdown
        assert "## Next Step" in markdown
        assert "None" not in markdown
        assert summary["is_valid_handoff"] is True

        line_count = summary["line_count"]
        assert isinstance(line_count, int)
        assert line_count >= 10


def test_day46_healthy_session_does_not_render_blocker_section() -> None:
    records = read_jsonl(FIXTURE_DIR / "healthy_session.jsonl")
    handoff = build_handoff_for_case("healthy_session", records)

    markdown = render_handoff_markdown(handoff)

    assert "## Blockers" not in markdown
    assert "## Do Not Redo" not in markdown


def test_day46_degraded_session_renders_blockers_and_do_not_redo() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    handoff = build_handoff_for_case("degraded_session", records)

    markdown = render_handoff_markdown(handoff)

    assert "## Blockers" in markdown
    assert "## Do Not Redo" in markdown
    assert "Failing loop" in markdown or "Repeated attempt" in markdown


def test_day46_markdown_output_is_bounded_for_replay_cases() -> None:
    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        handoff = build_handoff_for_case(path.stem, records)
        markdown = render_handoff_markdown(handoff)

        assert len(markdown) < 10_000
