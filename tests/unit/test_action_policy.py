from __future__ import annotations

from pilot_core.action_policy import (
    action_policy_summary,
    apply_action_policy,
    normalise_activation_mode,
    normalise_activation_modes,
    resolve_action_policy,
    strongest_mode_from_signals,
)
from pilot_core.constants import ActivationMode, SessionState, SignalName
from pilot_core.decision_engine import DecisionAction, DecisionReason, DecisionResult
from pilot_core.health import HealthComputation, compute_health_score
from pilot_core.warnings import (
    render_claude_additional_context,
    render_hook_stdout_payload,
    render_user_stderr,
)


def make_decision(
    *,
    action: DecisionAction = DecisionAction.PREPARE_HANDOFF,
    state: SessionState = SessionState.CRITICAL,
    health_score: float = 0.25,
) -> DecisionResult:
    return DecisionResult(
        action=action,
        reason=DecisionReason.STOP_HOOK_CRITICAL,
        state=state,
        health_score=health_score,
        should_inject_context=True,
        additional_context="Pilot context: critical test context.",
        should_notify_user=True,
        user_notification="Pilot warning: critical test notification.",
        should_prepare_handoff=action is DecisionAction.PREPARE_HANDOFF,
        handoff_reason="critical stop hook",
        cooldown_active=False,
        explanation="test decision",
    )


def make_health() -> HealthComputation:
    return compute_health_score(
        {
            SignalName.ERROR_CASCADE: {
                "signal_name": SignalName.ERROR_CASCADE,
                "score": 1.0,
                "fired": True,
            },
            SignalName.RATE_LIMIT: {
                "signal_name": SignalName.RATE_LIMIT,
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


def test_normalise_activation_mode_accepts_enum_and_string() -> None:
    assert normalise_activation_mode(ActivationMode.WARN) is ActivationMode.WARN
    assert normalise_activation_mode("action") is ActivationMode.ACTION


def test_normalise_activation_modes_overrides_defaults() -> None:
    modes = normalise_activation_modes({"rate_limit": "action"})

    assert modes[SignalName.RATE_LIMIT] is ActivationMode.ACTION
    assert modes[SignalName.ERROR_CASCADE] is ActivationMode.SHADOW


def test_strongest_mode_from_signals_returns_highest_rank() -> None:
    mode = strongest_mode_from_signals(
        [SignalName.ERROR_CASCADE, SignalName.RATE_LIMIT],
        activation_modes={
            SignalName.ERROR_CASCADE: ActivationMode.WARN,
            SignalName.RATE_LIMIT: ActivationMode.ACTION,
        },
    )

    assert mode is ActivationMode.ACTION


def test_resolve_action_policy_uses_strongest_fired_signal_mode() -> None:
    health = make_health()

    evaluation = resolve_action_policy(
        health,
        activation_modes={
            SignalName.ERROR_CASCADE: ActivationMode.WARN,
            SignalName.RATE_LIMIT: ActivationMode.ACTION,
        },
    )

    assert evaluation.effective_mode is ActivationMode.ACTION
    assert evaluation.source_signal is SignalName.RATE_LIMIT


def test_shadow_mode_suppresses_visible_output() -> None:
    decision = make_decision()
    health = make_health()

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes={SignalName.RATE_LIMIT: ActivationMode.SHADOW},
        default_mode=ActivationMode.SHADOW,
    )

    assert result.effective_mode is ActivationMode.SHADOW
    assert result.suppressed is True
    assert result.policy_decision.should_inject_context is False
    assert result.policy_decision.should_notify_user is False
    assert result.policy_decision.should_prepare_handoff is False
    assert render_claude_additional_context(result.policy_decision) is None
    assert render_user_stderr(result.policy_decision) is None
    assert render_hook_stdout_payload(result.policy_decision) == {}


def test_warn_mode_allows_warnings_but_suppresses_handoff() -> None:
    decision = make_decision()
    health = make_health()

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes={SignalName.RATE_LIMIT: ActivationMode.WARN},
    )

    assert result.effective_mode is ActivationMode.WARN
    assert result.suppressed is True
    assert result.policy_decision.should_inject_context is True
    assert result.policy_decision.should_notify_user is True
    assert result.policy_decision.should_prepare_handoff is False
    assert render_hook_stdout_payload(result.policy_decision) != {}


def test_action_mode_preserves_handoff_decision() -> None:
    decision = make_decision()
    health = make_health()

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes={SignalName.RATE_LIMIT: ActivationMode.ACTION},
    )

    assert result.effective_mode is ActivationMode.ACTION
    assert result.suppressed is False
    assert result.policy_decision is decision
    assert result.policy_decision.should_prepare_handoff is True


def test_warn_mode_does_not_modify_non_handoff_warning() -> None:
    decision = make_decision(action=DecisionAction.NOTIFY_USER)
    health = make_health()

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes={SignalName.RATE_LIMIT: ActivationMode.WARN},
    )

    assert result.policy_decision.action is DecisionAction.NOTIFY_USER
    assert result.suppressed is False


def test_action_policy_summary_is_serialisable() -> None:
    decision = make_decision()
    health = make_health()

    result = apply_action_policy(
        decision,
        health=health,
        activation_modes={SignalName.RATE_LIMIT: ActivationMode.ACTION},
    )

    summary = action_policy_summary(result)

    assert summary["effective_mode"] == "action"
    assert summary["policy_action"] == "prepare_handoff"
    assert summary["should_prepare_handoff"] is True
