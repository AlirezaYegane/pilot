from __future__ import annotations

from pilot_core.constants import SessionState
from pilot_core.decision_engine import DecisionAction, decide_next_action
from pilot_core.health import compute_health_score
from pilot_core.state_machine import transition_from_health_with_hysteresis
from pilot_core.warnings import (
    render_hook_stdout_payload,
    render_user_stderr,
    warning_summary,
)
from tests.integration.test_day35_full_signal_integration import (
    FIXTURE_DIR,
    evaluate_all_signals,
    read_jsonl,
)


def _decision_for_case(filename: str) -> tuple[DecisionAction, dict[str, str], str | None]:
    records = read_jsonl(FIXTURE_DIR / filename)
    signal_results = evaluate_all_signals(records)
    health = compute_health_score(signal_results)

    transition = transition_from_health_with_hysteresis(
        SessionState.HEALTHY,
        health,
    )
    decision = decide_next_action(
        transition,
        health=health,
        turn_index=10,
        at_stop_hook=True,
    )

    return decision.action, render_hook_stdout_payload(decision), render_user_stderr(decision)


def test_day40_safe_cases_do_not_emit_hook_payload() -> None:
    for filename in ("healthy_session.jsonl", "noisy_session.jsonl"):
        action, payload, stderr_text = _decision_for_case(filename)

        assert action in {DecisionAction.SILENT, DecisionAction.OBSERVE}
        assert payload == {}
        assert stderr_text is None


def test_day40_degraded_case_emits_warning_output() -> None:
    action, payload, stderr_text = _decision_for_case("degraded_session.jsonl")

    assert action in {
        DecisionAction.INJECT_CONTEXT,
        DecisionAction.NOTIFY_USER,
        DecisionAction.PREPARE_HANDOFF,
    }
    assert payload != {} or stderr_text is not None


def test_day40_warning_summary_matches_replay_cases() -> None:
    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        signal_results = evaluate_all_signals(records)
        health = compute_health_score(signal_results)

        transition = transition_from_health_with_hysteresis(
            SessionState.HEALTHY,
            health,
        )
        decision = decide_next_action(
            transition,
            health=health,
            turn_index=10,
            at_stop_hook=True,
        )
        summary = warning_summary(decision)

        assert isinstance(summary["has_additional_context"], bool)
        assert isinstance(summary["has_user_stderr"], bool)
        assert isinstance(summary["hook_payload_keys"], list)
