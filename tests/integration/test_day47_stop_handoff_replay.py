from __future__ import annotations

from pathlib import Path

from pilot_core.constants import ActivationMode, SessionState
from pilot_core.stop_handoff import build_stop_handoff_result
from tests.integration.test_day35_full_signal_integration import (
    FIXTURE_DIR,
    evaluate_all_signals,
    read_jsonl,
)


def test_day47_degraded_replay_generates_handoff_in_action_mode(tmp_path: Path) -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    signal_results = evaluate_all_signals(records)

    result = build_stop_handoff_result(
        signal_results,
        records=records,
        session_id="day47-degraded",
        task="Continue degraded replay case",
        current_state=SessionState.HEALTHY,
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
        handoff_dir=tmp_path,
        write_files=True,
        generated_at="2026-06-23T00:00:00+00:00",
    )

    assert result.should_generate_handoff
    assert result.markdown_path is not None
    assert result.markdown_path.exists()
    assert result.json_path is not None
    assert result.json_path.exists()
    assert result.runtime.should_prepare_handoff is True
    assert result.runtime.applied_policy.effective_mode is ActivationMode.ACTION


def test_day47_healthy_replay_does_not_generate_handoff(tmp_path: Path) -> None:
    records = read_jsonl(FIXTURE_DIR / "healthy_session.jsonl")
    signal_results = evaluate_all_signals(records)

    result = build_stop_handoff_result(
        signal_results,
        records=records,
        session_id="day47-healthy",
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
        handoff_dir=tmp_path,
        write_files=True,
    )

    assert not result.should_generate_handoff
    assert result.markdown_path is None
    assert result.json_path is None


def test_day47_degraded_replay_shadow_mode_stays_silent(tmp_path: Path) -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    signal_results = evaluate_all_signals(records)

    result = build_stop_handoff_result(
        signal_results,
        records=records,
        session_id="day47-shadow",
        default_mode=ActivationMode.SHADOW,
        at_stop_hook=True,
        handoff_dir=tmp_path,
        write_files=True,
    )

    assert not result.should_generate_handoff
    assert result.markdown_path is None
    assert result.json_path is None
    assert result.runtime.applied_policy.effective_mode is ActivationMode.SHADOW


def test_day47_generated_handoff_contains_blocker_context() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    signal_results = evaluate_all_signals(records)

    result = build_stop_handoff_result(
        signal_results,
        records=records,
        session_id="day47-content",
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
        generated_at="2026-06-23T00:00:00+00:00",
    )

    assert result.markdown is not None
    assert "## Blockers" in result.markdown
    assert "## Do Not Redo" in result.markdown
    assert "health" in result.markdown.lower()
