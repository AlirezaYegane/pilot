"""Policy runtime pipeline for Pilot.

Day 42 composes the pure Pilot policy layers into one hook-ready runtime result.

Pipeline:
- signal results -> health score
- health score -> hysteresis-safe state transition
- state transition -> decision engine result
- decision result -> action policy
- policy decision -> hook stdout payload and optional stderr text

This module is still side-effect free:
- it does not print
- it does not write to storage
- it does not call hooks
- it only returns a hook-ready result object
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pilot_core.action_policy import (
    AppliedActionPolicy,
    action_policy_summary,
    apply_action_policy,
)
from pilot_core.constants import ActivationMode, SessionState, SignalName
from pilot_core.decision_engine import DecisionResult, decide_next_action
from pilot_core.health import HealthComputation, compute_health_score
from pilot_core.state_machine import StateTransition, transition_from_health_with_hysteresis
from pilot_core.warnings import (
    render_hook_stdout_payload,
    render_user_stderr,
    warning_summary,
)


@dataclass(frozen=True)
class PolicyRuntimeResult:
    """Hook-ready output of Pilot's policy runtime pipeline."""

    health: HealthComputation
    transition: StateTransition
    decision: DecisionResult
    applied_policy: AppliedActionPolicy
    hook_payload: dict[str, str]
    user_stderr: str | None
    top_signals: tuple[SignalName, ...]

    @property
    def policy_decision(self) -> DecisionResult:
        """Return the decision after activation-mode policy is applied."""

        return self.applied_policy.policy_decision

    @property
    def should_emit_stdout(self) -> bool:
        """Return True when hook stdout should contain JSON payload."""

        return bool(self.hook_payload)

    @property
    def should_emit_stderr(self) -> bool:
        """Return True when hook stderr should show a user-facing warning."""

        return self.user_stderr is not None

    @property
    def should_prepare_handoff(self) -> bool:
        """Return True when the final policy decision allows handoff preparation."""

        return self.policy_decision.should_prepare_handoff


def top_signal_names(
    health: HealthComputation,
    *,
    limit: int = 3,
    fired_only: bool = False,
) -> tuple[SignalName, ...]:
    """Return top signal names for rendering and summaries."""

    if limit <= 0:
        return tuple()

    names: list[SignalName] = []

    for contribution in health.top_contributors:
        if contribution.weighted_badness <= 0:
            continue

        if fired_only and not contribution.fired:
            continue

        names.append(contribution.signal_name)

        if len(names) >= limit:
            break

    return tuple(names)


def run_policy_runtime(
    signal_results: Mapping[Any, object] | Sequence[object],
    *,
    current_state: SessionState = SessionState.HEALTHY,
    activation_modes: Mapping[Any, object] | None = None,
    default_mode: ActivationMode | str = ActivationMode.SHADOW,
    turn_index: int | None = None,
    last_warning_turn_index: int | None = None,
    at_stop_hook: bool = False,
    manual_handoff: bool = False,
    forced_handoff: bool = False,
    handoff_requested: bool = False,
    handoff_completed: bool = False,
) -> PolicyRuntimeResult:
    """Run the full pure policy runtime from signal results to hook output."""

    health = compute_health_score(signal_results)

    transition = transition_from_health_with_hysteresis(
        current_state,
        health,
        handoff_requested=handoff_requested,
        handoff_completed=handoff_completed,
    )

    decision = decide_next_action(
        transition,
        health=health,
        turn_index=turn_index,
        last_warning_turn_index=last_warning_turn_index,
        at_stop_hook=at_stop_hook,
        manual_handoff_requested=manual_handoff,
        force_handoff=forced_handoff,
    )

    applied_policy = apply_action_policy(
        decision,
        health=health,
        activation_modes=activation_modes,
        default_mode=default_mode,
    )

    rendered_signals = top_signal_names(health)

    hook_payload = render_hook_stdout_payload(
        applied_policy.policy_decision,
        top_signals=rendered_signals,
    )

    user_stderr = render_user_stderr(
        applied_policy.policy_decision,
        top_signals=rendered_signals,
    )

    return PolicyRuntimeResult(
        health=health,
        transition=transition,
        decision=decision,
        applied_policy=applied_policy,
        hook_payload=hook_payload,
        user_stderr=user_stderr,
        top_signals=rendered_signals,
    )


def policy_runtime_summary(result: PolicyRuntimeResult) -> dict[str, object]:
    """Return a serialisable summary for smoke scripts, tests, and future CLI."""

    return {
        "health": {
            "score": round(result.health.health_score, 4),
            "state": result.health.derived_state.value,
            "fired_count": result.health.fired_count,
            "observed_signal_count": result.health.observed_signal_count,
        },
        "transition": {
            "previous_state": result.transition.previous_state.value,
            "next_state": result.transition.next_state.value,
            "changed": result.transition.changed,
            "reason": result.transition.reason.value,
            "should_prepare_handoff": result.transition.should_prepare_handoff,
        },
        "decision": {
            "original_action": result.decision.action.value,
            "policy_action": result.policy_decision.action.value,
            "state": result.policy_decision.state.value,
            "should_prepare_handoff": result.policy_decision.should_prepare_handoff,
            "should_inject_context": result.policy_decision.should_inject_context,
            "should_notify_user": result.policy_decision.should_notify_user,
        },
        "policy": action_policy_summary(result.applied_policy),
        "warning": warning_summary(
            result.policy_decision,
            top_signals=result.top_signals,
        ),
        "hook": {
            "stdout_keys": sorted(result.hook_payload.keys()),
            "has_stdout": result.should_emit_stdout,
            "has_stderr": result.should_emit_stderr,
            "has_additional_context": "additionalContext" in result.hook_payload,
        },
        "top_signals": [signal.value for signal in result.top_signals],
    }
