from __future__ import annotations

from pilot_core.constants import SessionState
from pilot_core.health import compute_health_score
from pilot_core.state_machine import (
    apply_hysteresis_sequence,
    transition_from_health_with_hysteresis,
)
from tests.integration.test_day35_full_signal_integration import (
    FIXTURE_DIR,
    evaluate_all_signals,
    read_jsonl,
)


def test_day38_replay_cases_transition_with_hysteresis() -> None:
    expected_states: dict[str, set[SessionState]] = {
        "healthy_session": {SessionState.HEALTHY},
        "noisy_session": {SessionState.HEALTHY, SessionState.WATCHING},
        "ambiguous_session": {
            SessionState.HEALTHY,
            SessionState.WATCHING,
            SessionState.DEGRADING,
        },
        "degraded_session": {SessionState.DEGRADING, SessionState.CRITICAL},
    }

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        signal_results = evaluate_all_signals(records)
        health = compute_health_score(signal_results)

        transition = transition_from_health_with_hysteresis(
            SessionState.HEALTHY,
            health,
        )

        assert transition.next_state in expected_states[path.stem]


def test_day38_hysteresis_keeps_healthy_case_stable_under_small_noise() -> None:
    transitions = apply_hysteresis_sequence(
        SessionState.HEALTHY,
        (0.82, 0.79, 0.81, 0.78, 0.80, 0.77),
        hysteresis=0.05,
    )

    assert all(transition.next_state is SessionState.HEALTHY for transition in transitions)


def test_day38_hysteresis_keeps_watching_case_stable_near_boundary() -> None:
    transitions = apply_hysteresis_sequence(
        SessionState.WATCHING,
        (0.79, 0.81, 0.83, 0.78, 0.82, 0.84),
        hysteresis=0.05,
    )

    assert all(transition.next_state is SessionState.WATCHING for transition in transitions)


def test_day38_hysteresis_keeps_degrading_case_stable_near_boundary() -> None:
    transitions = apply_hysteresis_sequence(
        SessionState.DEGRADING,
        (0.59, 0.61, 0.63, 0.58, 0.62, 0.64),
        hysteresis=0.05,
    )

    assert all(transition.next_state is SessionState.DEGRADING for transition in transitions)


def test_day38_hysteresis_allows_real_recovery_and_real_degradation() -> None:
    transitions = apply_hysteresis_sequence(
        SessionState.DEGRADING,
        (0.62, 0.64, 0.66, 0.58, 0.54),
        hysteresis=0.05,
    )

    assert transitions[0].next_state is SessionState.DEGRADING
    assert transitions[1].next_state is SessionState.DEGRADING
    assert transitions[2].next_state is SessionState.WATCHING
    assert transitions[3].next_state is SessionState.WATCHING
    assert transitions[4].next_state is SessionState.DEGRADING
