from __future__ import annotations

import os
from pathlib import Path

from pilot_core.handoff import HandoffBlocker, HandoffDoNotRedo, HandoffSchema, handoff_to_json
from pilot_core.session_resume import (
    build_session_resume_result,
    handoff_artifact_candidates,
    load_handoff_artifact,
    load_latest_handoff_artifact,
    render_resume_context,
    resolve_handoff_dir_from_payload,
    session_resume_summary,
)


def make_handoff(session_id: str = "old-session") -> HandoffSchema:
    return HandoffSchema(
        session_id=session_id,
        generated_at="2026-06-23T00:00:00+00:00",
        task="Continue Day 48 implementation",
        progress="Stop hook generated a previous handoff.",
        blockers=(HandoffBlocker(description="A blocker from previous session"),),
        next_step="Load this handoff during SessionStart.",
        do_not_redo=(HandoffDoNotRedo(item="Do not repeat the failing loop"),),
        notes=("Resume flow should inject this into additionalContext.",),
    )


def test_handoff_artifact_candidates_are_newest_first_and_prefer_json(tmp_path: Path) -> None:
    old_md = tmp_path / "old.md"
    new_md = tmp_path / "new.md"
    new_json = tmp_path / "new.json"

    old_md.write_text("# old\n", encoding="utf-8")
    new_md.write_text("# new md\n", encoding="utf-8")
    new_json.write_text(handoff_to_json(make_handoff()), encoding="utf-8")

    os.utime(old_md, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new_md, ns=(2_000_000_000, 2_000_000_000))
    os.utime(new_json, ns=(2_000_000_000, 2_000_000_000))

    candidates = handoff_artifact_candidates(tmp_path)

    assert candidates[0] == new_json
    assert candidates[1] == new_md
    assert candidates[2] == old_md


def test_load_handoff_artifact_from_json_renders_markdown(tmp_path: Path) -> None:
    path = tmp_path / "handoff.json"
    path.write_text(handoff_to_json(make_handoff()), encoding="utf-8")

    artifact = load_handoff_artifact(path)

    assert artifact.is_json_backed
    assert artifact.handoff is not None
    assert artifact.handoff.task == "Continue Day 48 implementation"
    assert "# Pilot Handoff" in artifact.markdown
    assert "## Next Step" in artifact.markdown


def test_load_handoff_artifact_from_markdown_fallback(tmp_path: Path) -> None:
    path = tmp_path / "handoff.md"
    path.write_text("# Pilot Handoff\n\n## Next Step\nContinue.\n", encoding="utf-8")

    artifact = load_handoff_artifact(path)

    assert not artifact.is_json_backed
    assert artifact.handoff is None
    assert "Continue." in artifact.markdown


def test_load_latest_handoff_skips_invalid_json_and_uses_markdown(tmp_path: Path) -> None:
    markdown_path = tmp_path / "valid.md"
    bad_json_path = tmp_path / "bad.json"

    markdown_path.write_text("# Pilot Handoff\n", encoding="utf-8")
    bad_json_path.write_text("{not-json", encoding="utf-8")

    os.utime(markdown_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(bad_json_path, ns=(2_000_000_000, 2_000_000_000))

    artifact = load_latest_handoff_artifact(tmp_path)

    assert artifact is not None
    assert artifact.path == markdown_path
    assert artifact.source_format == "markdown"


def test_build_session_resume_result_returns_empty_without_handoff(tmp_path: Path) -> None:
    result = build_session_resume_result(session_id="new-session", handoff_dir=tmp_path)

    assert not result.has_resume_context
    assert result.hook_payload == {}
    assert result.reason == "no_previous_handoff"


def test_build_session_resume_result_emits_additional_context(tmp_path: Path) -> None:
    path = tmp_path / "handoff.json"
    path.write_text(handoff_to_json(make_handoff()), encoding="utf-8")

    result = build_session_resume_result(session_id="new-session", handoff_dir=tmp_path)

    assert result.has_resume_context
    assert result.reason == "loaded_previous_handoff"

    context = result.hook_payload["additionalContext"]
    assert "Pilot resume context from previous handoff" in context
    assert "Continue Day 48 implementation" in context
    assert "Do Not Redo" in context


def test_render_resume_context_bounds_long_markdown(tmp_path: Path) -> None:
    path = tmp_path / "handoff.md"
    path.write_text("# Pilot Handoff\n" + ("x" * 2_000), encoding="utf-8")
    artifact = load_handoff_artifact(path)

    context = render_resume_context(artifact, max_chars=300)

    assert len(context) <= 300
    assert "[handoff truncated]" in context


def test_resolve_handoff_dir_from_payload_uses_cwd_for_relative_path(tmp_path: Path) -> None:
    payload = {"cwd": str(tmp_path), "handoff_dir": ".pilot/handoffs"}

    resolved = resolve_handoff_dir_from_payload(payload)

    assert resolved == tmp_path / ".pilot" / "handoffs"


def test_session_resume_summary_is_serialisable(tmp_path: Path) -> None:
    path = tmp_path / "handoff.json"
    path.write_text(handoff_to_json(make_handoff()), encoding="utf-8")

    result = build_session_resume_result(session_id="new-session", handoff_dir=tmp_path)
    summary = session_resume_summary(result)

    assert summary["has_resume_context"] is True
    assert summary["artifact_format"] == "json"
    assert summary["reason"] == "loaded_previous_handoff"
