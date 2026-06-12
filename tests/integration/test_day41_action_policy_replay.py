from __future__ import annotations

from collections.abc import Mapping

from pilot_core.action_policy import apply_action_policy
from pilot_core.constants import ActivationMode, SessionState, SignalName
from pilot_core.decision_engine import DecisionResult, decide_next_action
from pilot_core.health import HealthComputation, compute_health_score
from pilot_core.state_machine import transition_from_health_with_hysteresis
from pilot_core.warnings import render_hook_stdout_payload, render_user_stderr
from tests.integration.test_day35_full_signal_integration import (
    FIXTURE_DIR,
    evaluate_all_signals,
    read_jsonl,
)


def _decision_for_case(filename: str) -> tuple[DecisionResult, HealthComputation]:
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

    return decision, health


def _all_modes(mode: ActivationMode) -> Mapping[SignalName, ActivationMode]:
    return {signal: mode for signal in SignalName}


def test_day41_healthy_session_stays_silent_even_in_action_mode() -> None:
    decision, health = _decision_for_case("healthy_session.jsonl")

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes=_all_modes(ActivationMode.ACTION),
    )

    assert result.policy_decision.is_silent
    assert render_hook_stdout_payload(result.policy_decision) == {}
    assert render_user_stderr(result.policy_decision) is None


def test_day41_degraded_session_shadow_mode_surfaces_nothing() -> None:
    decision, health = _decision_for_case("degraded_session.jsonl")

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes=_all_modes(ActivationMode.SHADOW),
    )

    assert result.effective_mode is ActivationMode.SHADOW
    assert result.suppressed is True
    assert result.policy_decision.should_prepare_handoff is False
    assert render_hook_stdout_payload(result.policy_decision) == {}
    assert render_user_stderr(result.policy_decision) is None


def test_day41_degraded_session_warn_mode_suppresses_handoff_only() -> None:
    decision, health = _decision_for_case("degraded_session.jsonl")

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes=_all_modes(ActivationMode.WARN),
    )

    assert result.effective_mode is ActivationMode.WARN
    assert result.policy_decision.should_prepare_handoff is False
    assert result.policy_decision.should_inject_context or result.policy_decision.should_notify_user
    assert render_hook_stdout_payload(result.policy_decision) != {}


def test_day41_degraded_session_action_mode_allows_handoff() -> None:
    decision, health = _decision_for_case("degraded_session.jsonl")

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes=_all_modes(ActivationMode.ACTION),
    )

    assert result.effective_mode is ActivationMode.ACTION
    assert result.suppressed is False
    assert result.policy_decision.should_prepare_handoff is True


def test_day41_rate_limit_action_overrides_other_warn_modes() -> None:
    decision, health = _decision_for_case("degraded_session.jsonl")

    activation_modes = {signal: ActivationMode.WARN for signal in SignalName}
    activation_modes[SignalName.RATE_LIMIT] = ActivationMode.ACTION

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes=activation_modes,
    )

    assert result.effective_mode is ActivationMode.ACTION
    assert result.policy_decision.should_prepare_handoff is True
