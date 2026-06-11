from __future__ import annotations

from pilot_core.constants import SessionState
from pilot_core.decision_engine import DecisionAction, decide_next_action
from pilot_core.health import compute_health_score
from pilot_core.state_machine import transition_from_health_with_hysteresis
from tests.integration.test_day35_full_signal_integration import (
    FIXTURE_DIR,
    evaluate_all_signals,
    read_jsonl,
)


def test_day39_replay_cases_produce_expected_decision_classes() -> None:
    expected_actions: dict[str, set[DecisionAction]] = {
        "healthy_session": {DecisionAction.SILENT, DecisionAction.OBSERVE},
        "noisy_session": {DecisionAction.SILENT, DecisionAction.OBSERVE},
        "ambiguous_session": {
            DecisionAction.SILENT,
            DecisionAction.OBSERVE,
            DecisionAction.INJECT_CONTEXT,
        },
        "degraded_session": {
            DecisionAction.INJECT_CONTEXT,
            DecisionAction.NOTIFY_USER,
            DecisionAction.PREPARE_HANDOFF,
        },
    }

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        signal_results = evaluate_all_signals(records)
        health = compute_health_score(signal_results)

        transition = transition_from_health_with_hysteresis(
            SessionState.HEALTHY,
            health,
        )
        decision = decide_next_action(transition, health=health)

        assert decision.action in expected_actions[path.stem]
        assert decision.health_score == health.health_score
        assert decision.explanation.strip()


def test_day39_degraded_session_prepares_handoff_at_stop_hook() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    signal_results = evaluate_all_signals(records)
    health = compute_health_score(signal_results)

    transition = transition_from_health_with_hysteresis(
        SessionState.HEALTHY,
        health,
    )
    decision = decide_next_action(
        transition,
        health=health,
        at_stop_hook=True,
    )

    if transition.next_state is SessionState.CRITICAL:
        assert decision.action is DecisionAction.PREPARE_HANDOFF
        assert decision.should_prepare_handoff is True
    else:
        assert decision.action in {
            DecisionAction.INJECT_CONTEXT,
            DecisionAction.PREPARE_HANDOFF,
        }


def test_day39_cooldown_does_not_change_safe_sessions() -> None:
    for filename in ("healthy_session.jsonl", "noisy_session.jsonl"):
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
            last_warning_turn_index=9,
        )

        assert decision.action in {DecisionAction.SILENT, DecisionAction.OBSERVE}
        assert decision.should_prepare_handoff is False
