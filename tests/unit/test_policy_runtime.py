from __future__ import annotations

from pilot_core.constants import ActivationMode, SessionState, SignalName
from pilot_core.policy_runtime import (
    policy_runtime_summary,
    run_policy_runtime,
    top_signal_names,
)


def all_modes(mode: ActivationMode) -> dict[SignalName, ActivationMode]:
    """Return one activation mode for all signals."""

    return {signal: mode for signal in SignalName}


def critical_signal_results() -> dict[SignalName, dict[str, object]]:
    """Return strong fired signal results that should make the session critical."""

    return {
        signal: {
            "signal_name": signal,
            "score": 1.0,
            "confidence": 1.0,
            "fired": True,
        }
        for signal in SignalName
    }


def healthy_signal_results() -> dict[SignalName, dict[str, object]]:
    """Return quiet signal results."""

    return {
        signal: {
            "signal_name": signal,
            "score": 0.0,
            "confidence": 1.0,
            "fired": False,
        }
        for signal in SignalName
    }


def test_top_signal_names_returns_highest_contributors() -> None:
    result = run_policy_runtime(
        critical_signal_results(),
        activation_modes=all_modes(ActivationMode.ACTION),
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
    )

    names = top_signal_names(result.health, limit=3)

    assert len(names) == 3
    assert all(isinstance(name, SignalName) for name in names)


def test_healthy_shadow_runtime_is_silent() -> None:
    result = run_policy_runtime(
        healthy_signal_results(),
        default_mode=ActivationMode.SHADOW,
    )

    assert result.health.derived_state is SessionState.HEALTHY
    assert result.policy_decision.is_silent
    assert result.hook_payload == {}
    assert result.user_stderr is None
    assert result.should_emit_stdout is False
    assert result.should_emit_stderr is False


def test_critical_shadow_runtime_suppresses_visible_output() -> None:
    result = run_policy_runtime(
        critical_signal_results(),
        activation_modes=all_modes(ActivationMode.SHADOW),
        default_mode=ActivationMode.SHADOW,
        at_stop_hook=True,
        turn_index=10,
    )

    assert result.health.derived_state is SessionState.CRITICAL
    assert result.applied_policy.effective_mode is ActivationMode.SHADOW
    assert result.applied_policy.suppressed is True
    assert result.hook_payload == {}
    assert result.user_stderr is None
    assert result.should_prepare_handoff is False


def test_critical_warn_runtime_suppresses_handoff_but_surfaces_warning() -> None:
    result = run_policy_runtime(
        critical_signal_results(),
        activation_modes=all_modes(ActivationMode.WARN),
        default_mode=ActivationMode.WARN,
        at_stop_hook=True,
        turn_index=10,
    )

    assert result.applied_policy.effective_mode is ActivationMode.WARN
    assert result.policy_decision.should_prepare_handoff is False
    assert result.applied_policy.suppressed is True
    assert result.hook_payload or result.user_stderr is not None


def test_critical_action_runtime_keeps_handoff_and_hook_payload() -> None:
    result = run_policy_runtime(
        critical_signal_results(),
        activation_modes=all_modes(ActivationMode.ACTION),
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
        turn_index=10,
    )

    assert result.applied_policy.effective_mode is ActivationMode.ACTION
    assert result.policy_decision.should_prepare_handoff is True
    assert "additionalContext" in result.hook_payload
    assert result.should_emit_stdout is True


def test_policy_runtime_summary_is_serialisable_shape() -> None:
    result = run_policy_runtime(
        critical_signal_results(),
        activation_modes=all_modes(ActivationMode.ACTION),
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
        turn_index=10,
    )

    summary = policy_runtime_summary(result)

    assert summary["health"]
    assert summary["transition"]
    assert summary["decision"]
    assert summary["policy"]
    assert summary["warning"]
    assert summary["hook"]
    assert summary["top_signals"]
