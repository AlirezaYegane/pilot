"""Day 49 handoff replay quality smoke report."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RawRecord = dict[str, object]


def main() -> None:
    """Run handoff quality review over replay cases."""

    from pilot_core.constants import ActivationMode, SessionState
    from pilot_core.handoff_quality import (
        handoff_quality_summary,
        review_handoff_artifact,
        review_handoff_markdown,
    )
    from pilot_core.session_resume import generate_session_resume_from_payload
    from pilot_core.stop_handoff import build_stop_handoff_result
    from tests.integration.test_day35_full_signal_integration import (
        FIXTURE_DIR,
        evaluate_all_signals,
        read_jsonl,
    )

    report: dict[str, object] = {}

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        signal_results = tuple(evaluate_all_signals(records).values())

        result = build_stop_handoff_result(
            signal_results,
            records=records,
            session_id=f"day49-smoke-{path.stem}",
            task=f"Continue from replay case: {path.stem}",
            current_state=SessionState.HEALTHY,
            default_mode=ActivationMode.ACTION,
            at_stop_hook=True,
            write_files=False,
            generated_at="2026-06-23T00:00:00+00:00",
        )

        case_report: dict[str, object] = {
            "generated": result.should_generate_handoff,
            "reason": result.reason,
            "runtime_action": result.runtime.policy_decision.action.value,
            "health_score": round(result.runtime.health.health_score, 4),
            "state": result.runtime.transition.next_state.value,
        }

        if result.handoff is not None and result.markdown is not None:
            review = review_handoff_markdown(result.handoff, markdown=result.markdown)
            case_report["quality"] = handoff_quality_summary(review)

        report[path.stem] = case_report

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        handoff_dir = tmp_path / ".pilot" / "handoffs"
        degraded_records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
        degraded_signals = tuple(evaluate_all_signals(degraded_records).values())

        artifact_result = build_stop_handoff_result(
            degraded_signals,
            records=degraded_records,
            session_id="day49-smoke-artifact",
            task="Continue Day 49 smoke artifact cycle.",
            current_state=SessionState.HEALTHY,
            default_mode=ActivationMode.ACTION,
            at_stop_hook=True,
            handoff_dir=handoff_dir,
            write_files=True,
            generated_at="2026-06-23T00:00:00+00:00",
        )

        artifact_report: dict[str, object] = {
            "generated": artifact_result.should_generate_handoff,
            "markdown_path_exists": bool(
                artifact_result.markdown_path and artifact_result.markdown_path.exists()
            ),
            "json_path_exists": bool(
                artifact_result.json_path and artifact_result.json_path.exists()
            ),
        }

        if artifact_result.markdown_path is not None:
            artifact_report["markdown_quality"] = handoff_quality_summary(
                review_handoff_artifact(artifact_result.markdown_path)
            )

        if artifact_result.json_path is not None:
            artifact_report["json_quality"] = handoff_quality_summary(
                review_handoff_artifact(artifact_result.json_path)
            )

        resume = generate_session_resume_from_payload(
            {
                "session_id": "day49-smoke-resume",
                "cwd": str(tmp_path),
                "handoff_dir": str(handoff_dir),
            },
            record_session=False,
        )

        artifact_report["resume"] = {
            "has_resume_context": resume.has_resume_context,
            "reason": resume.reason,
            "should_emit_stdout": resume.should_emit_stdout,
        }

        report["artifact_cycle"] = artifact_report

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
