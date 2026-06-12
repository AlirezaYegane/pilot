from __future__ import annotations

from collections.abc import Mapping

from pilot_core.constants import ActivationMode, SessionState, SignalName
from pilot_core.policy_runtime import PolicyRuntimeResult, run_policy_runtime
from tests.integration.test_day35_full_signal_integration import (
    FIXTURE_DIR,
    evaluate_all_signals,
    read_jsonl,
)


def all_modes(mode: ActivationMode) -> dict[SignalName, ActivationMode]:
    """Return one activation mode for all signals."""

    return {signal: mode for signal in SignalName}


def _runtime_for_case(
    filename: str,
    *,
    mode: ActivationMode,
) -> PolicyRuntimeResult:
    records = read_jsonl(FIXTURE_DIR / filename)
    signal_results = evaluate_all_signals(records)

    return run_policy_runtime(
        signal_results,
        current_state=SessionState.HEALTHY,
        activation_modes=all_modes(mode),
        default_mode=mode,
        at_stop_hook=True,
        turn_index=10,
    )


def test_day42_healthy_session_stays_silent_in_action_mode() -> None:
    result = _runtime_for_case("healthy_session.jsonl", mode=ActivationMode.ACTION)

    assert result.health.derived_state is SessionState.HEALTHY
    assert result.hook_payload == {}
    assert result.user_stderr is None
    assert result.should_prepare_handoff is False


def test_day42_degraded_session_shadow_mode_surfaces_nothing() -> None:
    result = _runtime_for_case("degraded_session.jsonl", mode=ActivationMode.SHADOW)

    assert result.health.fired_count >= 5
    assert result.applied_policy.effective_mode is ActivationMode.SHADOW
    assert result.hook_payload == {}
    assert result.user_stderr is None
    assert result.should_prepare_handoff is False


def test_day42_degraded_session_warn_mode_suppresses_handoff() -> None:
    result = _runtime_for_case("degraded_session.jsonl", mode=ActivationMode.WARN)

    assert result.health.fired_count >= 5
    assert result.applied_policy.effective_mode is ActivationMode.WARN
    assert result.policy_decision.should_prepare_handoff is False
    assert result.applied_policy.suppressed is True


def test_day42_degraded_session_action_mode_allows_handoff_payload() -> None:
    result = _runtime_for_case("degraded_session.jsonl", mode=ActivationMode.ACTION)

    assert result.health.fired_count >= 5
    assert result.applied_policy.effective_mode is ActivationMode.ACTION
    assert result.policy_decision.should_prepare_handoff is True
    assert "additionalContext" in result.hook_payload


def test_day42_noisy_and_ambiguous_do_not_emit_hook_payload() -> None:
    for filename in ("noisy_session.jsonl", "ambiguous_session.jsonl"):
        result = _runtime_for_case(filename, mode=ActivationMode.ACTION)

        assert result.should_prepare_handoff is False
        assert result.hook_payload == {}


def test_day42_runtime_accepts_string_activation_modes() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    signal_results = evaluate_all_signals(records)

    activation_modes: Mapping[object, object] = {signal.value: "action" for signal in SignalName}

    result = run_policy_runtime(
        signal_results,
        activation_modes=activation_modes,
        default_mode="action",
        at_stop_hook=True,
        turn_index=10,
    )

    assert result.applied_policy.effective_mode is ActivationMode.ACTION
    assert result.should_prepare_handoff is True
