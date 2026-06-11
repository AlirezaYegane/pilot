from __future__ import annotations

from pilot_core.constants import SessionState, SignalName
from pilot_core.decision_engine import (
    DecisionAction,
    DecisionReason,
    decide_next_action,
    decision_summary,
    is_warning_in_cooldown,
    render_additional_context,
)
from pilot_core.health import compute_health_score
from pilot_core.state_machine import transition_session_state


def test_is_warning_in_cooldown_without_turns_is_false() -> None:
    assert is_warning_in_cooldown(turn_index=None, last_warning_turn_index=1) is False
    assert is_warning_in_cooldown(turn_index=5, last_warning_turn_index=None) is False


def test_is_warning_in_cooldown_detects_recent_warning() -> None:
    assert (
        is_warning_in_cooldown(
            turn_index=10,
            last_warning_turn_index=8,
            cooldown_turns=3,
        )
        is True
    )


def test_is_warning_in_cooldown_allows_after_cooldown() -> None:
    assert (
        is_warning_in_cooldown(
            turn_index=10,
            last_warning_turn_index=7,
            cooldown_turns=3,
        )
        is False
    )


def test_healthy_state_is_silent() -> None:
    transition = transition_session_state(SessionState.HEALTHY, health_score=0.95)
    decision = decide_next_action(transition)

    assert decision.action is DecisionAction.SILENT
    assert decision.reason is DecisionReason.HEALTHY
    assert decision.should_inject_context is False
    assert decision.should_notify_user is False
    assert decision.should_prepare_handoff is False


def test_watching_state_observes_silently() -> None:
    transition = transition_session_state(SessionState.HEALTHY, health_score=0.70)
    decision = decide_next_action(transition)

    assert decision.action is DecisionAction.OBSERVE
    assert decision.reason is DecisionReason.WATCHING
    assert decision.is_silent is True


def test_degrading_state_injects_gentle_context() -> None:
    health = compute_health_score(
        {
            SignalName.ERROR_CASCADE: {
                "signal_name": SignalName.ERROR_CASCADE,
                "score": 0.8,
                "fired": True,
            },
            SignalName.REPEATED_CALLS: {
                "signal_name": SignalName.REPEATED_CALLS,
                "score": 0.7,
                "fired": True,
            },
        }
    )
    transition = transition_session_state(SessionState.HEALTHY, health_score=0.50)
    decision = decide_next_action(transition, health=health)

    assert decision.action is DecisionAction.INJECT_CONTEXT
    assert decision.reason is DecisionReason.DEGRADING
    assert decision.should_inject_context is True
    assert decision.additional_context is not None
    assert "degradation" in decision.additional_context
    assert decision.should_notify_user is False


def test_critical_state_notifies_user_and_injects_context() -> None:
    health = compute_health_score(
        {
            SignalName.RATE_LIMIT: {
                "signal_name": SignalName.RATE_LIMIT,
                "score": 1.0,
                "fired": True,
            },
            SignalName.ERROR_CASCADE: {
                "signal_name": SignalName.ERROR_CASCADE,
                "score": 1.0,
                "fired": True,
            },
            SignalName.TOKEN_BURN: {
                "signal_name": SignalName.TOKEN_BURN,
                "score": 1.0,
                "fired": True,
            },
        }
    )
    transition = transition_session_state(SessionState.HEALTHY, health_score=0.20)
    decision = decide_next_action(transition, health=health)

    assert decision.action is DecisionAction.NOTIFY_USER
    assert decision.reason is DecisionReason.CRITICAL
    assert decision.should_inject_context is True
    assert decision.should_notify_user is True
    assert decision.user_notification is not None
    assert "critical" in decision.user_notification


def test_warning_cooldown_suppresses_degrading_warning() -> None:
    transition = transition_session_state(SessionState.HEALTHY, health_score=0.50)
    decision = decide_next_action(
        transition,
        turn_index=10,
        last_warning_turn_index=8,
        warning_cooldown_turns=3,
    )

    assert decision.action is DecisionAction.COOLDOWN
    assert decision.reason is DecisionReason.WARNING_COOLDOWN
    assert decision.cooldown_active is True
    assert decision.should_inject_context is False


def test_handoff_pending_prepares_handoff() -> None:
    transition = transition_session_state(
        SessionState.CRITICAL,
        health_score=0.20,
        handoff_requested=True,
    )
    decision = decide_next_action(transition)

    assert decision.action is DecisionAction.PREPARE_HANDOFF
    assert decision.reason is DecisionReason.HANDOFF_PENDING
    assert decision.should_prepare_handoff is True
    assert decision.handoff_reason == "state_handoff_pending"


def test_stop_hook_critical_prepares_handoff() -> None:
    transition = transition_session_state(SessionState.DEGRADING, health_score=0.20)
    decision = decide_next_action(transition, at_stop_hook=True)

    assert transition.next_state is SessionState.CRITICAL
    assert decision.action is DecisionAction.PREPARE_HANDOFF
    assert decision.reason is DecisionReason.STOP_HOOK_CRITICAL
    assert decision.should_prepare_handoff is True


def test_manual_handoff_bypasses_cooldown() -> None:
    transition = transition_session_state(SessionState.HEALTHY, health_score=0.95)
    decision = decide_next_action(
        transition,
        manual_handoff_requested=True,
        turn_index=10,
        last_warning_turn_index=9,
    )

    assert decision.action is DecisionAction.PREPARE_HANDOFF
    assert decision.reason is DecisionReason.MANUAL_HANDOFF
    assert decision.cooldown_active is False
    assert decision.should_prepare_handoff is True


def test_forced_handoff_bypasses_state() -> None:
    transition = transition_session_state(SessionState.HEALTHY, health_score=0.95)
    decision = decide_next_action(transition, force_handoff=True)

    assert decision.action is DecisionAction.PREPARE_HANDOFF
    assert decision.reason is DecisionReason.FORCED_HANDOFF
    assert decision.state is SessionState.HANDOFF_PENDING


def test_render_additional_context_for_healthy_is_empty() -> None:
    assert (
        render_additional_context(
            state=SessionState.HEALTHY,
            health_score=0.95,
        )
        == ""
    )


def test_decision_summary_is_serialisable() -> None:
    transition = transition_session_state(SessionState.HEALTHY, health_score=0.70)
    decision = decide_next_action(transition)
    summary = decision_summary(decision)

    assert summary["action"] == "observe"
    assert summary["state"] == "watching"
    assert summary["should_inject_context"] is False
