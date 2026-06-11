from __future__ import annotations

import pytest

from pilot_core.constants import Defaults, SessionState
from pilot_core.state_machine import (
    apply_hysteresis_sequence,
    hysteresis_state_from_health_score,
    state_from_health_score,
    transition_session_state,
    transition_session_state_with_hysteresis,
)


def test_deterministic_state_from_health_score_still_uses_raw_boundaries() -> None:
    assert state_from_health_score(0.80) is SessionState.HEALTHY
    assert state_from_health_score(0.79) is SessionState.WATCHING
    assert state_from_health_score(0.60) is SessionState.WATCHING
    assert state_from_health_score(0.59) is SessionState.DEGRADING
    assert state_from_health_score(0.40) is SessionState.DEGRADING
    assert state_from_health_score(0.39) is SessionState.CRITICAL


def test_existing_transition_api_remains_deterministic() -> None:
    transition = transition_session_state(
        SessionState.HEALTHY,
        health_score=0.79,
    )

    assert transition.previous_state is SessionState.HEALTHY
    assert transition.next_state is SessionState.WATCHING
    assert transition.changed is True


def test_healthy_does_not_drop_to_watching_inside_hysteresis_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.HEALTHY,
        0.77,
        hysteresis=0.05,
    )

    assert state is SessionState.HEALTHY


def test_healthy_drops_to_watching_below_lower_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.HEALTHY,
        0.74,
        hysteresis=0.05,
    )

    assert state is SessionState.WATCHING


def test_watching_does_not_recover_to_healthy_inside_upper_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.WATCHING,
        0.83,
        hysteresis=0.05,
    )

    assert state is SessionState.WATCHING


def test_watching_recovers_to_healthy_above_upper_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.WATCHING,
        0.86,
        hysteresis=0.05,
    )

    assert state is SessionState.HEALTHY


def test_watching_does_not_drop_to_degrading_inside_lower_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.WATCHING,
        0.56,
        hysteresis=0.05,
    )

    assert state is SessionState.WATCHING


def test_watching_drops_to_degrading_below_lower_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.WATCHING,
        0.54,
        hysteresis=0.05,
    )

    assert state is SessionState.DEGRADING


def test_degrading_does_not_recover_to_watching_inside_upper_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.DEGRADING,
        0.63,
        hysteresis=0.05,
    )

    assert state is SessionState.DEGRADING


def test_degrading_recovers_to_watching_above_upper_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.DEGRADING,
        0.66,
        hysteresis=0.05,
    )

    assert state is SessionState.WATCHING


def test_degrading_does_not_drop_to_critical_inside_lower_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.DEGRADING,
        0.36,
        hysteresis=0.05,
    )

    assert state is SessionState.DEGRADING


def test_degrading_drops_to_critical_below_lower_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.DEGRADING,
        0.34,
        hysteresis=0.05,
    )

    assert state is SessionState.CRITICAL


def test_critical_does_not_recover_inside_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.CRITICAL,
        0.43,
        hysteresis=0.05,
    )

    assert state is SessionState.CRITICAL


def test_critical_recovers_above_upper_buffer() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.CRITICAL,
        0.46,
        hysteresis=0.05,
    )

    assert state is SessionState.DEGRADING


def test_handoff_pending_and_handed_off_remain_sticky() -> None:
    assert (
        hysteresis_state_from_health_score(SessionState.HANDOFF_PENDING, 0.99)
        is SessionState.HANDOFF_PENDING
    )
    assert (
        hysteresis_state_from_health_score(SessionState.HANDED_OFF, 0.99) is SessionState.HANDED_OFF
    )


def test_transition_with_hysteresis_mentions_buffer_in_explanation() -> None:
    transition = transition_session_state_with_hysteresis(
        SessionState.HEALTHY,
        health_score=0.77,
        hysteresis=0.05,
    )

    assert transition.next_state is SessionState.HEALTHY
    assert transition.changed is False
    assert "hysteresis=0.05" in transition.explanation


def test_transition_with_hysteresis_still_respects_handoff_request() -> None:
    transition = transition_session_state_with_hysteresis(
        SessionState.CRITICAL,
        health_score=0.20,
        handoff_requested=True,
    )

    assert transition.next_state is SessionState.HANDOFF_PENDING
    assert transition.should_prepare_handoff is True


def test_transition_with_hysteresis_still_respects_handoff_completed() -> None:
    transition = transition_session_state_with_hysteresis(
        SessionState.HANDOFF_PENDING,
        health_score=0.99,
        handoff_completed=True,
    )

    assert transition.next_state is SessionState.HANDED_OFF
    assert transition.is_terminal is True


def test_apply_hysteresis_sequence_prevents_boundary_flapping() -> None:
    scores = (0.81, 0.79, 0.82, 0.78, 0.81, 0.79)
    transitions = apply_hysteresis_sequence(
        SessionState.HEALTHY,
        scores,
        hysteresis=0.05,
    )

    assert [transition.next_state for transition in transitions] == [
        SessionState.HEALTHY,
        SessionState.HEALTHY,
        SessionState.HEALTHY,
        SessionState.HEALTHY,
        SessionState.HEALTHY,
        SessionState.HEALTHY,
    ]


def test_apply_hysteresis_sequence_eventually_changes_after_real_drop() -> None:
    scores = (0.81, 0.78, 0.76, 0.74, 0.73)
    transitions = apply_hysteresis_sequence(
        SessionState.HEALTHY,
        scores,
        hysteresis=0.05,
    )

    assert transitions[-1].next_state is SessionState.WATCHING
    assert any(transition.is_escalation for transition in transitions)


def test_zero_hysteresis_matches_deterministic_boundary_behavior() -> None:
    state = hysteresis_state_from_health_score(
        SessionState.HEALTHY,
        0.79,
        hysteresis=0.0,
    )

    assert state is SessionState.WATCHING


def test_invalid_hysteresis_values_raise() -> None:
    invalid_hysteresis_values = [-0.01, 0.20]

    for hysteresis in invalid_hysteresis_values:
        with pytest.raises(ValueError):
            hysteresis_state_from_health_score(
                current_state=SessionState.HEALTHY,
                health_score=0.80,
                hysteresis=hysteresis,
            )


def test_default_hysteresis_matches_project_default() -> None:
    transition = transition_session_state_with_hysteresis(
        SessionState.HEALTHY,
        health_score=Defaults.HEALTH_HEALTHY_MIN - 0.01,
    )

    assert Defaults.STATE_HYSTERESIS == 0.05
    assert transition.next_state is SessionState.HEALTHY
