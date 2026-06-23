from __future__ import annotations

from pathlib import Path

from pilot_core.handoff import HandoffBlocker, HandoffDoNotRedo, HandoffSchema
from pilot_core.render.handoff_md import (
    HandoffMarkdownOptions,
    HandoffMarkdownStyle,
    render_handoff_markdown,
)
from pilot_core.session_resume import generate_session_resume_from_payload, session_resume_summary
from pilot_core.stop_handoff import DEFAULT_STOP_HANDOFF_DIR, write_stop_handoff_artifacts


def make_previous_handoff(session_id: str = "previous-session") -> HandoffSchema:
    return HandoffSchema(
        session_id=session_id,
        generated_at="2026-06-23T00:00:00+00:00",
        task="Finish stop-hook handoff integration",
        progress="Day 47 generated markdown and JSON artifacts.",
        blockers=(HandoffBlocker(description="Need SessionStart resume flow"),),
        next_step="Load this handoff from SessionStart and continue cleanly.",
        do_not_redo=(HandoffDoNotRedo(item="Do not restart without reading handoff"),),
        notes=("This artifact should become additionalContext.",),
    )


def test_day48_session_start_loads_day47_json_artifact(tmp_path: Path) -> None:
    handoff_dir = tmp_path / DEFAULT_STOP_HANDOFF_DIR
    handoff = make_previous_handoff()
    markdown = render_handoff_markdown(
        handoff,
        options=HandoffMarkdownOptions(style=HandoffMarkdownStyle.FULL),
    )

    markdown_path, json_path = write_stop_handoff_artifacts(
        handoff=handoff,
        markdown=markdown,
        handoff_dir=handoff_dir,
    )

    assert markdown_path.exists()
    assert json_path.exists()

    result = generate_session_resume_from_payload(
        {"session_id": "new-session", "cwd": str(tmp_path)},
        record_session=False,
    )

    assert result.has_resume_context
    assert result.artifact is not None
    assert result.artifact.path == json_path
    assert result.artifact.source_format == "json"

    context = result.hook_payload["additionalContext"]
    assert "Finish stop-hook handoff integration" in context
    assert "Load this handoff from SessionStart" in context
    assert "Do Not Redo" in context


def test_day48_session_start_is_silent_without_previous_handoff(tmp_path: Path) -> None:
    result = generate_session_resume_from_payload(
        {"session_id": "new-session", "cwd": str(tmp_path)},
        record_session=False,
    )

    assert not result.has_resume_context
    assert result.hook_payload == {}
    assert result.reason == "no_previous_handoff"


def test_day48_session_start_supports_explicit_handoff_dir(tmp_path: Path) -> None:
    handoff_dir = tmp_path / "custom-handoffs"
    handoff = make_previous_handoff(session_id="explicit-dir")
    markdown = render_handoff_markdown(handoff)

    write_stop_handoff_artifacts(
        handoff=handoff,
        markdown=markdown,
        handoff_dir=handoff_dir,
    )

    result = generate_session_resume_from_payload(
        {
            "session_id": "new-session",
            "cwd": str(tmp_path),
            "handoff_dir": str(handoff_dir),
        },
        record_session=False,
    )

    assert result.has_resume_context
    assert result.artifact is not None
    assert result.artifact.path.parent == handoff_dir


def test_day48_session_resume_summary_reports_loaded_handoff(tmp_path: Path) -> None:
    handoff_dir = tmp_path / DEFAULT_STOP_HANDOFF_DIR
    handoff = make_previous_handoff()
    markdown = render_handoff_markdown(handoff)

    write_stop_handoff_artifacts(
        handoff=handoff,
        markdown=markdown,
        handoff_dir=handoff_dir,
    )

    result = generate_session_resume_from_payload(
        {"session_id": "new-session", "cwd": str(tmp_path)},
        record_session=False,
    )
    summary = session_resume_summary(result)

    assert summary["has_resume_context"] is True
    assert summary["should_emit_stdout"] is True
    assert summary["artifact_format"] == "json"

    context_char_count = summary["context_char_count"]
    assert isinstance(context_char_count, int)
    assert context_char_count > 0

    handoff_summary = summary["handoff"]
    assert isinstance(handoff_summary, dict)
    assert handoff_summary["is_valid"] is True
