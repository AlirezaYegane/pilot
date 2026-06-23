from __future__ import annotations

import pytest

from pilot_core.handoff import (
    HandoffBlocker,
    HandoffBlockerSeverity,
    HandoffDecision,
    HandoffDoNotRedo,
    HandoffFileChange,
    HandoffFileStatus,
    HandoffSchema,
)
from pilot_core.render.handoff_md import (
    HandoffMarkdownOptions,
    HandoffMarkdownStyle,
    handoff_markdown_summary,
    render_handoff_markdown,
)


def make_full_handoff() -> HandoffSchema:
    return HandoffSchema(
        session_id="session-day46",
        generated_at="2026-06-23T00:00:00+00:00",
        task="Implement Day 46 markdown renderer",
        progress="Schema, extractor, and blocker extraction are ready.",
        decisions=(
            HandoffDecision(
                title="Keep renderer pure",
                rationale="Stop hook integration belongs to Day 47.",
                alternatives_rejected=("write files directly", "call hooks from renderer"),
            ),
        ),
        files_modified=(
            HandoffFileChange(
                path="pilot_core/render/handoff_md.py",
                status=HandoffFileStatus.CREATED,
                reason="core markdown renderer",
            ),
            HandoffFileChange(
                path="tests/unit/test_handoff_markdown.py",
                status=HandoffFileStatus.CREATED,
                reason="renderer tests",
                important=True,
            ),
        ),
        blockers=(
            HandoffBlocker(
                description="Stop hook integration is not wired yet",
                severity=HandoffBlockerSeverity.WARNING,
                evidence="Day 47 owns stop hook integration.",
            ),
        ),
        next_step="Integrate renderer with stop hook.",
        do_not_redo=(
            HandoffDoNotRedo(
                item="Do not wire stop hook before renderer tests are stable",
                reason="Day 46 only owns markdown rendering.",
            ),
        ),
        notes=("Markdown output should stay concise and deterministic.",),
    )


def test_render_handoff_markdown_has_stable_core_sections() -> None:
    markdown = render_handoff_markdown(make_full_handoff())

    assert markdown.startswith("# Pilot Handoff\n")
    assert "## Metadata" in markdown
    assert "## Task" in markdown
    assert "Implement Day 46 markdown renderer" in markdown
    assert "## Progress" in markdown
    assert "## Decisions" in markdown
    assert "## Files Modified" in markdown
    assert "## Blockers" in markdown
    assert "## Next Step" in markdown
    assert "## Do Not Redo" in markdown


def test_render_handoff_markdown_is_deterministic() -> None:
    handoff = make_full_handoff()

    first = render_handoff_markdown(handoff)
    second = render_handoff_markdown(handoff)

    assert first == second


def test_render_handoff_markdown_omits_empty_optional_sections_by_default() -> None:
    handoff = HandoffSchema(
        task="Tiny handoff",
        progress="No optional records",
        next_step="Continue",
        generated_at="2026-06-23T00:00:00+00:00",
    )

    markdown = render_handoff_markdown(handoff)

    assert "## Decisions" not in markdown
    assert "## Files Modified" not in markdown
    assert "## Blockers" not in markdown
    assert "## Do Not Redo" not in markdown
    assert "## Notes" not in markdown


def test_render_handoff_markdown_can_include_empty_sections() -> None:
    handoff = HandoffSchema(
        task="Tiny handoff",
        progress="No optional records",
        next_step="Continue",
        generated_at="2026-06-23T00:00:00+00:00",
    )

    markdown = render_handoff_markdown(
        handoff,
        options=HandoffMarkdownOptions(include_empty_sections=True),
    )

    assert "## Decisions" in markdown
    assert "_None._" in markdown


def test_render_handoff_markdown_full_style_includes_rejected_alternatives() -> None:
    markdown = render_handoff_markdown(
        make_full_handoff(),
        options=HandoffMarkdownOptions(style=HandoffMarkdownStyle.FULL),
    )

    assert "Rejected:" in markdown
    assert "call hooks from renderer" in markdown


def test_render_handoff_markdown_truncates_long_text() -> None:
    handoff = HandoffSchema(
        task="x" * 500,
        progress="Progress is short",
        next_step="Continue",
        generated_at="2026-06-23T00:00:00+00:00",
    )

    markdown = render_handoff_markdown(
        handoff,
        options=HandoffMarkdownOptions(max_text_chars=120),
    )

    assert "... [truncated]" in markdown
    assert len(markdown) < 700


def test_handoff_markdown_summary_is_serialisable() -> None:
    handoff = make_full_handoff()
    markdown = render_handoff_markdown(handoff)

    summary = handoff_markdown_summary(handoff, markdown=markdown)

    assert summary["has_metadata"] is True
    assert summary["has_decisions"] is True
    assert summary["has_files_modified"] is True
    assert summary["has_blockers"] is True
    assert summary["has_do_not_redo"] is True
    assert summary["is_valid_handoff"] is True
    assert isinstance(summary["line_count"], int)


def test_render_handoff_markdown_rejects_bad_options() -> None:
    with pytest.raises(ValueError):
        render_handoff_markdown(
            make_full_handoff(),
            options=HandoffMarkdownOptions(max_section_items=0),
        )

    with pytest.raises(ValueError):
        render_handoff_markdown(
            make_full_handoff(),
            options=HandoffMarkdownOptions(max_text_chars=20),
        )
