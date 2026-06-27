from __future__ import annotations

from pathlib import Path

from pilot_core.handoff import (
    HandoffBlocker,
    HandoffDoNotRedo,
    HandoffFileChange,
    HandoffSchema,
    handoff_to_json,
)
from pilot_core.handoff_quality import (
    handoff_quality_summary,
    review_handoff_artifact,
    review_handoff_markdown,
    review_handoff_markdown_text,
)
from pilot_core.render.handoff_md import render_handoff_markdown


def make_handoff() -> HandoffSchema:
    return HandoffSchema(
        session_id="quality-test",
        generated_at="2026-06-23T00:00:00+00:00",
        task="Continue Day 49 handoff quality review.",
        progress="Generated a stop-hook handoff and reviewed the summary quality.",
        files_modified=(
            HandoffFileChange(
                path="pilot_core/handoff_quality.py",
                reason="quality review helper",
            ),
        ),
        blockers=(
            HandoffBlocker(
                description="Replay quality review was not implemented yet.",
                evidence="Day 49 roadmap requires handoff replay tests.",
            ),
        ),
        next_step="Continue by running the replay quality smoke script and then commit the Day 49 branch.",
        do_not_redo=(
            HandoffDoNotRedo(
                item="Do not manually inspect only one handoff.",
                reason="Replay quality must cover generated artifacts.",
            ),
        ),
        notes=("Use generated markdown, not hand-written summaries.",),
    )


def test_valid_handoff_markdown_passes_quality_review() -> None:
    handoff = make_handoff()
    markdown = render_handoff_markdown(handoff)

    review = review_handoff_markdown(handoff, markdown=markdown)

    assert review.passed
    assert review.score >= 0.80
    assert review.error_count == 0
    assert review.required_heading_count == 4


def test_missing_required_sections_fail_review() -> None:
    review = review_handoff_markdown_text("# Pilot Handoff\n\nOnly a title.\n")

    assert not review.passed
    assert review.error_count >= 1
    assert any(issue.code == "missing_required_heading" for issue in review.issues)


def test_schema_blockers_require_blocker_section() -> None:
    handoff = make_handoff()
    markdown = """
# Pilot Handoff

## Task
Continue Day 49.

## Progress
Progress exists.

## Next Step
Continue by running tests.
""".strip()

    review = review_handoff_markdown(handoff, markdown=markdown)

    assert not review.passed
    assert any(issue.code == "missing_blockers_section" for issue in review.issues)
    assert any(issue.code == "missing_do_not_redo_section" for issue in review.issues)


def test_quality_summary_is_serialisable() -> None:
    review = review_handoff_markdown(make_handoff())
    summary = handoff_quality_summary(review)

    assert summary["passed"] is True
    assert isinstance(summary["score"], float)
    assert isinstance(summary["issues"], list)


def test_review_json_artifact_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "handoff.json"
    path.write_text(handoff_to_json(make_handoff()), encoding="utf-8")

    review = review_handoff_artifact(path)

    assert review.passed
    assert review.source_format == "schema"


def test_review_markdown_artifact_fallback(tmp_path: Path) -> None:
    path = tmp_path / "handoff.md"
    path.write_text(render_handoff_markdown(make_handoff()), encoding="utf-8")

    review = review_handoff_artifact(path)

    assert review.passed
    assert review.source_format == "markdown"
