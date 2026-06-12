"""Action policy layer for Pilot activation modes.

Day 41 applies Pilot's activation modes to pure decision-engine results.

The decision engine answers: "what should happen?"
The warning renderer answers: "how should it be formatted?"
The action policy answers: "is this action allowed under shadow/warn/action?"

Activation modes:
- shadow: compute internally, surface nothing
- warn: allow warnings/additionalContext, suppress handoff actions
- action: allow the full decision, including handoff preparation

This module is pure and side-effect free. It does not print, write to storage,
or call hooks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pilot_core.constants import (
    DEFAULT_SIGNAL_ACTIVATION_MODES,
    ActivationMode,
    SignalName,
    parse_activation_mode,
    parse_signal_name,
)
from pilot_core.decision_engine import DecisionAction, DecisionReason, DecisionResult
from pilot_core.health import HealthComputation, SignalContribution

ACTIVATION_MODE_RANK: dict[ActivationMode, int] = {
    ActivationMode.SHADOW: 0,
    ActivationMode.WARN: 1,
    ActivationMode.ACTION: 2,
}


@dataclass(frozen=True)
class SignalActivation:
    """Activation mode chosen for one signal."""

    signal_name: SignalName
    mode: ActivationMode
    score: float
    fired: bool
    weighted_badness: float


@dataclass(frozen=True)
class ActionPolicyEvaluation:
    """Resolved activation-mode policy for a decision."""

    effective_mode: ActivationMode
    source_signal: SignalName | None
    signal_activations: tuple[SignalActivation, ...]
    explanation: str


@dataclass(frozen=True)
class AppliedActionPolicy:
    """Decision after activation-mode policy has been applied."""

    original_decision: DecisionResult
    policy_decision: DecisionResult
    evaluation: ActionPolicyEvaluation
    suppressed: bool
    suppression_reason: str | None

    @property
    def effective_mode(self) -> ActivationMode:
        """Return the resolved activation mode."""

        return self.evaluation.effective_mode

    @property
    def should_surface(self) -> bool:
        """Return True when policy allows user/Claude-visible output."""

        return (
            self.effective_mode is not ActivationMode.SHADOW and not self.policy_decision.is_silent
        )


def activation_mode_rank(mode: ActivationMode) -> int:
    """Return comparable rank for an activation mode."""

    return ACTIVATION_MODE_RANK[mode]


def normalise_activation_mode(value: ActivationMode | str) -> ActivationMode:
    """Normalise an activation-mode value from enum or string."""

    if isinstance(value, ActivationMode):
        return value

    return parse_activation_mode(value)


def _normalise_signal_name(value: object) -> SignalName:
    """Normalise a signal-name key from enum or string."""

    if isinstance(value, SignalName):
        return value

    if isinstance(value, str):
        return parse_signal_name(value)

    raise ValueError(f"Invalid signal name: {value!r}")


def normalise_activation_modes(
    activation_modes: Mapping[Any, object] | None = None,
) -> dict[SignalName, ActivationMode]:
    """Return a complete signal activation-mode map."""

    resolved = dict(DEFAULT_SIGNAL_ACTIVATION_MODES)

    if activation_modes is None:
        return resolved

    for raw_signal_name, raw_mode in activation_modes.items():
        signal_name = _normalise_signal_name(raw_signal_name)

        if isinstance(raw_mode, ActivationMode | str):
            resolved[signal_name] = normalise_activation_mode(raw_mode)
        else:
            raise ValueError(f"Invalid activation mode: {raw_mode!r}")

    return resolved


def _signal_activation_from_contribution(
    contribution: SignalContribution,
    *,
    mode: ActivationMode,
) -> SignalActivation:
    """Convert a health contribution into signal activation metadata."""

    return SignalActivation(
        signal_name=contribution.signal_name,
        mode=mode,
        score=contribution.score,
        fired=contribution.fired,
        weighted_badness=contribution.weighted_badness,
    )


def resolve_action_policy(
    health: HealthComputation | None,
    *,
    activation_modes: Mapping[Any, object] | None = None,
    default_mode: ActivationMode | str = ActivationMode.SHADOW,
    fired_only: bool = True,
) -> ActionPolicyEvaluation:
    """Resolve the effective activation mode from health contributions.

    The strongest activation mode among fired/top signals wins.
    If no signal is available, the explicit default mode is used.
    """

    resolved_modes = normalise_activation_modes(activation_modes)
    fallback_mode = normalise_activation_mode(default_mode)

    if health is None:
        return ActionPolicyEvaluation(
            effective_mode=fallback_mode,
            source_signal=None,
            signal_activations=tuple(),
            explanation=f"no health computation available; mode={fallback_mode.value}",
        )

    signal_activations: list[SignalActivation] = []
    effective_mode = fallback_mode
    source_signal: SignalName | None = None

    for contribution in health.top_contributors:
        if fired_only and not contribution.fired:
            continue

        mode = resolved_modes.get(contribution.signal_name, fallback_mode)
        activation = _signal_activation_from_contribution(contribution, mode=mode)
        signal_activations.append(activation)

        if activation_mode_rank(mode) > activation_mode_rank(effective_mode):
            effective_mode = mode
            source_signal = contribution.signal_name

    if not signal_activations:
        explanation = f"no fired signal selected policy; mode={fallback_mode.value}"
    elif source_signal is None:
        explanation = f"signals observed but default mode remains {fallback_mode.value}"
    else:
        explanation = f"mode={effective_mode.value} from signal={source_signal.value}"

    return ActionPolicyEvaluation(
        effective_mode=effective_mode,
        source_signal=source_signal,
        signal_activations=tuple(signal_activations),
        explanation=explanation,
    )


def _replace_decision(
    decision: DecisionResult,
    *,
    action: DecisionAction,
    reason: DecisionReason | None = None,
    should_inject_context: bool | None = None,
    additional_context: str | None | object = None,
    should_notify_user: bool | None = None,
    user_notification: str | None | object = None,
    should_prepare_handoff: bool | None = None,
    handoff_reason: str | None | object = None,
    cooldown_active: bool | None = None,
    explanation: str | None = None,
) -> DecisionResult:
    """Return a copy of a DecisionResult with selected fields replaced."""

    sentinel = object()

    resolved_additional_context = (
        decision.additional_context if additional_context is sentinel else additional_context
    )
    resolved_user_notification = (
        decision.user_notification if user_notification is sentinel else user_notification
    )
    resolved_handoff_reason = (
        decision.handoff_reason if handoff_reason is sentinel else handoff_reason
    )

    return DecisionResult(
        action=action,
        reason=reason or decision.reason,
        state=decision.state,
        health_score=decision.health_score,
        should_inject_context=(
            decision.should_inject_context
            if should_inject_context is None
            else should_inject_context
        ),
        additional_context=(
            resolved_additional_context
            if isinstance(resolved_additional_context, str) or resolved_additional_context is None
            else None
        ),
        should_notify_user=(
            decision.should_notify_user if should_notify_user is None else should_notify_user
        ),
        user_notification=(
            resolved_user_notification
            if isinstance(resolved_user_notification, str) or resolved_user_notification is None
            else None
        ),
        should_prepare_handoff=(
            decision.should_prepare_handoff
            if should_prepare_handoff is None
            else should_prepare_handoff
        ),
        handoff_reason=(
            resolved_handoff_reason
            if isinstance(resolved_handoff_reason, str) or resolved_handoff_reason is None
            else None
        ),
        cooldown_active=decision.cooldown_active if cooldown_active is None else cooldown_active,
        explanation=explanation or decision.explanation,
    )


def _shadow_decision(decision: DecisionResult) -> DecisionResult:
    """Return a decision suppressed by shadow mode."""

    action = (
        DecisionAction.SILENT
        if decision.action is DecisionAction.SILENT
        else DecisionAction.OBSERVE
    )

    return DecisionResult(
        action=action,
        reason=DecisionReason.WARNING_COOLDOWN,
        state=decision.state,
        health_score=decision.health_score,
        should_inject_context=False,
        additional_context=None,
        should_notify_user=False,
        user_notification=None,
        should_prepare_handoff=False,
        handoff_reason=None,
        cooldown_active=True,
        explanation=(
            "action policy shadow mode suppressed visible output; "
            f"original_action={decision.action.value}"
        ),
    )


def _warn_decision(decision: DecisionResult) -> DecisionResult:
    """Return a warning-only decision with handoff suppressed."""

    if not decision.should_prepare_handoff:
        return decision

    user_notification = decision.user_notification or (
        "Pilot warn mode: handoff would be prepared in action mode, "
        "but this policy only allows warnings."
    )

    action = (
        DecisionAction.NOTIFY_USER
        if user_notification
        else DecisionAction.INJECT_CONTEXT
        if decision.additional_context
        else DecisionAction.OBSERVE
    )

    return DecisionResult(
        action=action,
        reason=decision.reason,
        state=decision.state,
        health_score=decision.health_score,
        should_inject_context=bool(decision.additional_context),
        additional_context=decision.additional_context,
        should_notify_user=bool(user_notification),
        user_notification=user_notification,
        should_prepare_handoff=False,
        handoff_reason=None,
        cooldown_active=decision.cooldown_active,
        explanation=(
            f"action policy warn mode suppressed handoff; original_action={decision.action.value}"
        ),
    )


def apply_action_policy(
    decision: DecisionResult,
    *,
    health: HealthComputation | None = None,
    activation_modes: Mapping[Any, object] | None = None,
    default_mode: ActivationMode | str = ActivationMode.SHADOW,
) -> AppliedActionPolicy:
    """Apply activation-mode policy to a decision-engine result."""

    evaluation = resolve_action_policy(
        health,
        activation_modes=activation_modes,
        default_mode=default_mode,
    )

    if evaluation.effective_mode is ActivationMode.SHADOW:
        policy_decision = _shadow_decision(decision)
        return AppliedActionPolicy(
            original_decision=decision,
            policy_decision=policy_decision,
            evaluation=evaluation,
            suppressed=True,
            suppression_reason="shadow mode suppresses all visible output",
        )

    if evaluation.effective_mode is ActivationMode.WARN:
        policy_decision = _warn_decision(decision)
        suppressed = decision.should_prepare_handoff and not policy_decision.should_prepare_handoff
        return AppliedActionPolicy(
            original_decision=decision,
            policy_decision=policy_decision,
            evaluation=evaluation,
            suppressed=suppressed,
            suppression_reason="warn mode suppresses handoff" if suppressed else None,
        )

    return AppliedActionPolicy(
        original_decision=decision,
        policy_decision=decision,
        evaluation=evaluation,
        suppressed=False,
        suppression_reason=None,
    )


def action_policy_summary(result: AppliedActionPolicy) -> dict[str, object]:
    """Return a serialisable action-policy summary."""

    return {
        "effective_mode": result.effective_mode.value,
        "source_signal": (
            result.evaluation.source_signal.value
            if result.evaluation.source_signal is not None
            else None
        ),
        "original_action": result.original_decision.action.value,
        "policy_action": result.policy_decision.action.value,
        "state": result.policy_decision.state.value,
        "health_score": round(result.policy_decision.health_score, 4),
        "suppressed": result.suppressed,
        "suppression_reason": result.suppression_reason,
        "should_inject_context": result.policy_decision.should_inject_context,
        "should_notify_user": result.policy_decision.should_notify_user,
        "should_prepare_handoff": result.policy_decision.should_prepare_handoff,
        "explanation": result.policy_decision.explanation,
    }


def strongest_mode_from_signals(
    signals: Sequence[SignalName | str],
    *,
    activation_modes: Mapping[Any, object] | None = None,
    default_mode: ActivationMode | str = ActivationMode.SHADOW,
) -> ActivationMode:
    """Resolve the strongest mode from an explicit list of signal names."""

    resolved_modes = normalise_activation_modes(activation_modes)
    fallback_mode = normalise_activation_mode(default_mode)
    effective_mode = fallback_mode

    for raw_signal in signals:
        signal_name = _normalise_signal_name(raw_signal)
        mode = resolved_modes.get(signal_name, fallback_mode)
        if activation_mode_rank(mode) > activation_mode_rank(effective_mode):
            effective_mode = mode

    return effective_mode
