from __future__ import annotations

import pytest

from pilot_core.constants import SessionState
from pilot_core.health import compute_health_score
from pilot_core.state_machine import (
    SessionStateMachine,
    StateTransitionReason,
    apply_hysteresis_sequence,
    state_from_health_score,
    state_rank,
    state_transition_summary,
    transition_from_health,
    transition_reason,
    transition_sequence_summary,
    transition_session_state,
)


def test_state_from_health_score_bands() -> None:
    cases: list[tuple[float, SessionState]] = [
        (1.00, SessionState.HEALTHY),
        (0.80, SessionState.HEALTHY),
        (0.79, SessionState.WATCHING),
        (0.60, SessionState.WATCHING),
        (0.59, SessionState.DEGRADING),
        (0.40, SessionState.DEGRADING),
        (0.39, SessionState.CRITICAL),
        (0.00, SessionState.CRITICAL),
    ]

    for health_score, expected_state in cases:
        assert state_from_health_score(health_score) is expected_state


def test_state_from_health_score_clamps_values() -> None:
    assert state_from_health_score(2.0) is SessionState.HEALTHY
    assert state_from_health_score(-1.0) is SessionState.CRITICAL


def test_state_rank_order() -> None:
    assert state_rank(SessionState.HEALTHY) < state_rank(SessionState.WATCHING)
    assert state_rank(SessionState.WATCHING) < state_rank(SessionState.DEGRADING)
    assert state_rank(SessionState.DEGRADING) < state_rank(SessionState.CRITICAL)
    assert state_rank(SessionState.CRITICAL) < state_rank(SessionState.HANDOFF_PENDING)
    assert state_rank(SessionState.HANDOFF_PENDING) < state_rank(SessionState.HANDED_OFF)


def test_transition_reason_for_escalation() -> None:
    reason = transition_reason(SessionState.HEALTHY, SessionState.WATCHING)

    assert reason is StateTransitionReason.ESCALATION


def test_transition_reason_for_recovery() -> None:
    reason = transition_reason(SessionState.CRITICAL, SessionState.DEGRADING)

    assert reason is StateTransitionReason.RECOVERY


def test_transition_reason_for_same_band() -> None:
    reason = transition_reason(SessionState.HEALTHY, SessionState.HEALTHY)

    assert reason is StateTransitionReason.HEALTH_BAND


def test_transition_reason_for_terminal_state() -> None:
    reason = transition_reason(SessionState.HANDED_OFF, SessionState.HANDED_OFF)

    assert reason is StateTransitionReason.TERMINAL


def test_transition_reason_for_forced_state() -> None:
    reason = transition_reason(
        SessionState.HEALTHY,
        SessionState.CRITICAL,
        forced=True,
    )

    assert reason is StateTransitionReason.FORCED


def test_transition_session_state_stays_healthy() -> None:
    transition = transition_session_state(
        SessionState.HEALTHY,
        health_score=0.95,
    )

    assert transition.previous_state is SessionState.HEALTHY
    assert transition.next_state is SessionState.HEALTHY
    assert transition.changed is False
    assert transition.reason is StateTransitionReason.HEALTH_BAND


def test_transition_session_state_escalates_to_watching() -> None:
    transition = transition_session_state(
        SessionState.HEALTHY,
        health_score=0.70,
    )

    assert transition.next_state is SessionState.WATCHING
    assert transition.changed is True
    assert transition.is_escalation is True


def test_transition_session_state_escalates_to_degrading() -> None:
    transition = transition_session_state(
        SessionState.HEALTHY,
        health_score=0.50,
    )

    assert transition.next_state is SessionState.DEGRADING
    assert transition.is_escalation is True


def test_transition_session_state_escalates_to_critical() -> None:
    transition = transition_session_state(
        SessionState.HEALTHY,
        health_score=0.20,
    )

    assert transition.next_state is SessionState.CRITICAL
    assert transition.is_escalation is True
    assert transition.should_prepare_handoff is True


def test_transition_session_state_recovers() -> None:
    transition = transition_session_state(
        SessionState.CRITICAL,
        health_score=0.90,
    )

    assert transition.next_state is SessionState.HEALTHY
    assert transition.is_recovery is True


def test_handoff_requested_moves_degrading_to_pending() -> None:
    transition = transition_session_state(
        SessionState.DEGRADING,
        health_score=0.50,
        handoff_requested=True,
    )

    assert transition.next_state is SessionState.HANDOFF_PENDING
    assert transition.reason is StateTransitionReason.HANDOFF_REQUESTED
    assert transition.should_prepare_handoff is True


def test_handoff_requested_moves_critical_to_pending() -> None:
    transition = transition_session_state(
        SessionState.CRITICAL,
        health_score=0.20,
        handoff_requested=True,
    )

    assert transition.next_state is SessionState.HANDOFF_PENDING
    assert transition.reason is StateTransitionReason.HANDOFF_REQUESTED


def test_handoff_requested_is_ignored_from_watching() -> None:
    transition = transition_session_state(
        SessionState.WATCHING,
        health_score=0.70,
        handoff_requested=True,
    )

    assert transition.next_state is SessionState.WATCHING
    assert transition.reason is StateTransitionReason.HEALTH_BAND


def test_handoff_pending_is_sticky_until_completed() -> None:
    transition = transition_session_state(
        SessionState.HANDOFF_PENDING,
        health_score=1.00,
    )

    assert transition.next_state is SessionState.HANDOFF_PENDING
    assert transition.changed is False


def test_handoff_completed_moves_to_handed_off() -> None:
    transition = transition_session_state(
        SessionState.HANDOFF_PENDING,
        health_score=1.00,
        handoff_completed=True,
    )

    assert transition.next_state is SessionState.HANDED_OFF
    assert transition.reason is StateTransitionReason.HANDOFF_COMPLETED
    assert transition.is_terminal is True


def test_handed_off_is_terminal() -> None:
    transition = transition_session_state(
        SessionState.HANDED_OFF,
        health_score=0.10,
    )

    assert transition.next_state is SessionState.HANDED_OFF
    assert transition.changed is False
    assert transition.is_terminal is True


def test_forced_state_overrides_normal_transition() -> None:
    transition = transition_session_state(
        SessionState.HEALTHY,
        health_score=1.00,
        forced_state=SessionState.CRITICAL,
    )

    assert transition.next_state is SessionState.CRITICAL
    assert transition.reason is StateTransitionReason.FORCED


def test_transition_from_health_uses_health_object() -> None:
    health = compute_health_score(
        {
            "error_cascade": {"signal_name": "error_cascade", "score": 1.0, "fired": True},
            "rate_limit": {"signal_name": "rate_limit", "score": 1.0, "fired": True},
            "token_burn": {"signal_name": "token_burn", "score": 1.0, "fired": True},
        }
    )

    transition = transition_from_health(SessionState.HEALTHY, health)

    assert transition.health_score == health.health_score
    assert transition.next_state is health.derived_state


def test_state_transition_summary_is_serialisable() -> None:
    transition = transition_session_state(
        SessionState.HEALTHY,
        health_score=0.20,
    )

    summary = state_transition_summary(transition)

    assert summary["previous_state"] == "healthy"
    assert summary["next_state"] == "critical"
    assert summary["changed"] is True
    assert summary["is_escalation"] is True


def test_transition_sequence_summary_returns_list() -> None:
    transitions = apply_hysteresis_sequence(
        SessionState.HEALTHY,
        (0.95, 0.70),
        hysteresis=0.05,
    )

    summary = transition_sequence_summary(transitions)

    assert isinstance(summary, list)
    assert len(summary) == 2


def test_session_state_machine_stores_state() -> None:
    machine = SessionStateMachine()

    first = machine.transition(health_score=0.70)
    second = machine.transition(health_score=0.20)

    assert first.next_state is SessionState.WATCHING
    assert second.next_state is SessionState.CRITICAL
    assert machine.state is SessionState.CRITICAL


def test_session_state_machine_supports_custom_initial_state() -> None:
    machine = SessionStateMachine(initial_state=SessionState.CRITICAL)

    transition = machine.transition(health_score=0.90)

    assert transition.previous_state is SessionState.CRITICAL
    assert transition.next_state is SessionState.HEALTHY
    assert machine.state is SessionState.HEALTHY


def test_session_state_machine_supports_hysteresis_transition() -> None:
    machine = SessionStateMachine(initial_state=SessionState.HEALTHY)

    transition = machine.transition_with_hysteresis(
        health_score=0.77,
        hysteresis=0.05,
    )

    assert transition.next_state is SessionState.HEALTHY
    assert machine.state is SessionState.HEALTHY


def test_invalid_state_rank_raises_for_unknown_state() -> None:
    with pytest.raises(KeyError):
        state_rank("bad-state")  # type: ignore[arg-type]
