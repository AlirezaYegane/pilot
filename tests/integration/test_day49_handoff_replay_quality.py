from __future__ import annotations

from pathlib import Path

from pilot_core.constants import ActivationMode, SessionState
from pilot_core.handoff_quality import review_handoff_artifact, review_handoff_markdown
from pilot_core.session_resume import generate_session_resume_from_payload
from pilot_core.stop_handoff import build_stop_handoff_result
from tests.integration.test_day35_full_signal_integration import (
    FIXTURE_DIR,
    evaluate_all_signals,
    read_jsonl,
)

RawRecord = dict[str, object]


def _records(case_name: str) -> list[RawRecord]:
    return read_jsonl(FIXTURE_DIR / f"{case_name}.jsonl")


def _signal_results(records: list[RawRecord]) -> tuple[object, ...]:
    return tuple(evaluate_all_signals(records).values())


def test_day49_degraded_replay_generates_quality_handoff() -> None:
    records = _records("degraded_session")

    result = build_stop_handoff_result(
        _signal_results(records),
        records=records,
        session_id="day49-degraded-quality",
        task="Continue degraded replay handoff quality review.",
        current_state=SessionState.HEALTHY,
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
        write_files=False,
        generated_at="2026-06-23T00:00:00+00:00",
    )

    assert result.should_generate_handoff
    assert result.handoff is not None
    assert result.markdown is not None

    review = review_handoff_markdown(result.handoff, markdown=result.markdown)

    assert review.passed
    assert review.score >= 0.80
    assert review.error_count == 0
    assert review.required_heading_count == 4


def test_day49_non_degraded_replays_do_not_generate_handoff_noise() -> None:
    for case_name in ("healthy_session", "noisy_session", "ambiguous_session"):
        records = _records(case_name)

        result = build_stop_handoff_result(
            _signal_results(records),
            records=records,
            session_id=f"day49-{case_name}",
            task=f"Review {case_name}",
            current_state=SessionState.HEALTHY,
            default_mode=ActivationMode.ACTION,
            at_stop_hook=True,
            write_files=False,
            generated_at="2026-06-23T00:00:00+00:00",
        )

        assert not result.should_generate_handoff
        assert result.handoff is None
        assert result.markdown is None


def test_day49_written_artifacts_pass_quality_review_and_resume(tmp_path: Path) -> None:
    records = _records("degraded_session")
    handoff_dir = tmp_path / ".pilot" / "handoffs"

    result = build_stop_handoff_result(
        _signal_results(records),
        records=records,
        session_id="day49-artifact-cycle",
        task="Continue Day 49 artifact cycle.",
        current_state=SessionState.HEALTHY,
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
        handoff_dir=handoff_dir,
        write_files=True,
        generated_at="2026-06-23T00:00:00+00:00",
    )

    assert result.should_generate_handoff
    assert result.markdown_path is not None
    assert result.json_path is not None
    assert result.markdown_path.exists()
    assert result.json_path.exists()

    markdown_review = review_handoff_artifact(result.markdown_path)
    json_review = review_handoff_artifact(result.json_path)

    assert markdown_review.passed
    assert json_review.passed

    resume = generate_session_resume_from_payload(
        {
            "session_id": "day49-new-session",
            "cwd": str(tmp_path),
            "handoff_dir": str(handoff_dir),
        },
        record_session=False,
    )

    assert resume.has_resume_context
    assert resume.reason == "loaded_previous_handoff"

    context = resume.hook_payload["additionalContext"]
    assert "Pilot resume context from previous handoff" in context
    assert "Continue Day 49 artifact cycle" in context


def test_day49_warn_mode_suppresses_handoff_generation() -> None:
    records = _records("degraded_session")

    result = build_stop_handoff_result(
        _signal_results(records),
        records=records,
        session_id="day49-warn-suppressed",
        task="Warn mode should not create a handoff artifact.",
        current_state=SessionState.HEALTHY,
        default_mode=ActivationMode.WARN,
        at_stop_hook=True,
        write_files=False,
        generated_at="2026-06-23T00:00:00+00:00",
    )

    assert not result.should_generate_handoff
    assert result.handoff is None
    assert result.markdown is None
    assert result.reason == "policy_did_not_request_handoff"
