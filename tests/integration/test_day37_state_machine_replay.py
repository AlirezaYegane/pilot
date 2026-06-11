from __future__ import annotations

from pilot_core.constants import SessionState
from pilot_core.health import compute_health_score
from pilot_core.state_machine import transition_from_health
from tests.integration.test_day35_full_signal_integration import (
    FIXTURE_DIR,
    evaluate_all_signals,
    read_jsonl,
)


def test_day37_healthy_replay_stays_healthy() -> None:
    records = read_jsonl(FIXTURE_DIR / "healthy_session.jsonl")
    health = compute_health_score(evaluate_all_signals(records))

    transition = transition_from_health(SessionState.HEALTHY, health)

    assert transition.next_state is SessionState.HEALTHY
    assert transition.changed is False
    assert transition.should_prepare_handoff is False


def test_day37_noisy_replay_does_not_escalate_to_degrading() -> None:
    records = read_jsonl(FIXTURE_DIR / "noisy_session.jsonl")
    health = compute_health_score(evaluate_all_signals(records))

    transition = transition_from_health(SessionState.HEALTHY, health)

    assert transition.next_state in {SessionState.HEALTHY, SessionState.WATCHING}
    assert transition.should_prepare_handoff is False


def test_day37_ambiguous_replay_does_not_become_critical() -> None:
    records = read_jsonl(FIXTURE_DIR / "ambiguous_session.jsonl")
    health = compute_health_score(evaluate_all_signals(records))

    transition = transition_from_health(SessionState.HEALTHY, health)

    assert transition.next_state is not SessionState.CRITICAL


def test_day37_degraded_replay_escalates() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    health = compute_health_score(evaluate_all_signals(records))

    transition = transition_from_health(SessionState.HEALTHY, health)

    assert transition.next_state in {SessionState.DEGRADING, SessionState.CRITICAL}
    assert transition.is_escalation is True


def test_day37_degraded_replay_can_request_handoff_after_escalation() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    health = compute_health_score(evaluate_all_signals(records))

    first = transition_from_health(SessionState.HEALTHY, health)
    second = transition_from_health(
        first.next_state,
        health,
        handoff_requested=True,
    )

    assert second.next_state is SessionState.HANDOFF_PENDING
    assert second.should_prepare_handoff is True
