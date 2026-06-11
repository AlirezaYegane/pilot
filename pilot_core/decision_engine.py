"""Decision engine for Pilot session policy.

Day 39 turns health + state transitions into concrete Pilot actions.

The decision engine is intentionally pure:
- it does not write to storage
- it does not call hooks
- it does not generate handoff summaries
- it only decides what should happen next

State behavior:
- healthy: silent
- watching: silent observe
- degrading: inject gentle additionalContext
- critical: inject stronger additionalContext and notify user
- handoff_pending: prepare handoff
- handed_off: no further action
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pilot_core.constants import Defaults, SessionState, SignalName
from pilot_core.health import HealthComputation
from pilot_core.state_machine import StateTransition


class DecisionAction(str, Enum):
    """Concrete action selected by Pilot."""

    SILENT = "silent"
    OBSERVE = "observe"
    INJECT_CONTEXT = "inject_context"
    NOTIFY_USER = "notify_user"
    PREPARE_HANDOFF = "prepare_handoff"
    COOLDOWN = "cooldown"


class DecisionReason(str, Enum):
    """Reason category for a decision."""

    HEALTHY = "healthy"
    WATCHING = "watching"
    DEGRADING = "degrading"
    CRITICAL = "critical"
    HANDOFF_PENDING = "handoff_pending"
    HANDED_OFF = "handed_off"
    STOP_HOOK_CRITICAL = "stop_hook_critical"
    MANUAL_HANDOFF = "manual_handoff"
    FORCED_HANDOFF = "forced_handoff"
    WARNING_COOLDOWN = "warning_cooldown"


@dataclass(frozen=True)
class DecisionResult:
    """Decision returned by Pilot's policy layer."""

    action: DecisionAction
    reason: DecisionReason
    state: SessionState
    health_score: float
    should_inject_context: bool
    additional_context: str | None
    should_notify_user: bool
    user_notification: str | None
    should_prepare_handoff: bool
    handoff_reason: str | None
    cooldown_active: bool
    explanation: str

    @property
    def is_silent(self) -> bool:
        """Return True when Pilot should not surface anything."""

        return self.action in {
            DecisionAction.SILENT,
            DecisionAction.OBSERVE,
            DecisionAction.COOLDOWN,
        }

    @property
    def is_intervention(self) -> bool:
        """Return True when Pilot should actively intervene."""

        return self.action in {
            DecisionAction.INJECT_CONTEXT,
            DecisionAction.NOTIFY_USER,
            DecisionAction.PREPARE_HANDOFF,
        }


def is_warning_in_cooldown(
    *,
    turn_index: int | None,
    last_warning_turn_index: int | None,
    cooldown_turns: int = Defaults.DEFAULT_WARNING_COOLDOWN_TURNS,
) -> bool:
    """Return True when a warning should be suppressed by cooldown."""

    if cooldown_turns < 0:
        raise ValueError("cooldown_turns must be greater than or equal to 0")

    if turn_index is None or last_warning_turn_index is None:
        return False

    return turn_index - last_warning_turn_index < cooldown_turns


def _top_signal_names(
    health: HealthComputation | None, *, limit: int = 3
) -> tuple[SignalName, ...]:
    """Return the most important signal names from health computation."""

    if health is None:
        return tuple()

    names: list[SignalName] = []

    for contribution in health.top_contributors:
        if contribution.weighted_badness <= 0:
            continue
        names.append(contribution.signal_name)
        if len(names) >= limit:
            break

    return tuple(names)


def _format_signal_list(signals: tuple[SignalName, ...]) -> str:
    """Return a compact human-readable signal list."""

    if not signals:
        return "no dominant signal"

    return ", ".join(signal.value for signal in signals)


def render_additional_context(
    *,
    state: SessionState,
    health_score: float,
    top_signals: tuple[SignalName, ...] = tuple(),
) -> str:
    """Render additionalContext text for Claude Code."""

    signal_text = _format_signal_list(top_signals)

    if state is SessionState.DEGRADING:
        return (
            "Pilot detected signs of session degradation "
            f"(health={health_score:.2f}; signals={signal_text}). "
            "Before continuing, briefly summarize progress, verify the current blocker, "
            "and avoid repeating failed tool calls."
        )

    if state is SessionState.CRITICAL:
        return (
            "Pilot detected critical session degradation "
            f"(health={health_score:.2f}; signals={signal_text}). "
            "Stop expanding the solution blindly. Summarize the current state, "
            "identify the failing loop, and prepare for a clean handoff if needed."
        )

    if state is SessionState.HANDOFF_PENDING:
        return (
            "Pilot marked this session as handoff_pending. Prepare a concise handoff "
            "summary with progress, modified files, blockers, and what not to redo."
        )

    return ""


def render_user_notification(
    *,
    state: SessionState,
    health_score: float,
    top_signals: tuple[SignalName, ...] = tuple(),
) -> str:
    """Render a user-facing notification for critical states."""

    signal_text = _format_signal_list(top_signals)

    if state is SessionState.CRITICAL:
        return (
            "Pilot warning: this session looks critical "
            f"(health={health_score:.2f}; signals={signal_text}). "
            "Consider stopping soon and creating a clean handoff."
        )

    if state is SessionState.HANDOFF_PENDING:
        return "Pilot handoff pending: the session should be summarized before continuing."

    return ""


def _build_decision(
    *,
    action: DecisionAction,
    reason: DecisionReason,
    state: SessionState,
    health_score: float,
    additional_context: str | None = None,
    user_notification: str | None = None,
    should_prepare_handoff: bool = False,
    handoff_reason: str | None = None,
    cooldown_active: bool = False,
) -> DecisionResult:
    """Build a DecisionResult consistently."""

    should_inject_context = additional_context is not None and additional_context.strip() != ""
    should_notify_user = user_notification is not None and user_notification.strip() != ""

    explanation = (
        f"decision={action.value} state={state.value} "
        f"health={health_score:.2f} reason={reason.value}"
    )

    return DecisionResult(
        action=action,
        reason=reason,
        state=state,
        health_score=health_score,
        should_inject_context=should_inject_context,
        additional_context=additional_context if should_inject_context else None,
        should_notify_user=should_notify_user,
        user_notification=user_notification if should_notify_user else None,
        should_prepare_handoff=should_prepare_handoff,
        handoff_reason=handoff_reason,
        cooldown_active=cooldown_active,
        explanation=explanation,
    )


def decide_next_action(
    transition: StateTransition,
    *,
    health: HealthComputation | None = None,
    turn_index: int | None = None,
    last_warning_turn_index: int | None = None,
    warning_cooldown_turns: int = Defaults.DEFAULT_WARNING_COOLDOWN_TURNS,
    at_stop_hook: bool = False,
    manual_handoff_requested: bool = False,
    force_handoff: bool = False,
) -> DecisionResult:
    """Return Pilot's next policy action for a state transition."""

    state = transition.next_state
    health_score = health.health_score if health is not None else transition.health_score
    top_signals = _top_signal_names(health)

    cooldown_active = is_warning_in_cooldown(
        turn_index=turn_index,
        last_warning_turn_index=last_warning_turn_index,
        cooldown_turns=warning_cooldown_turns,
    )

    if force_handoff:
        context = render_additional_context(
            state=SessionState.HANDOFF_PENDING,
            health_score=health_score,
            top_signals=top_signals,
        )
        return _build_decision(
            action=DecisionAction.PREPARE_HANDOFF,
            reason=DecisionReason.FORCED_HANDOFF,
            state=SessionState.HANDOFF_PENDING,
            health_score=health_score,
            additional_context=context,
            should_prepare_handoff=True,
            handoff_reason="forced_handoff",
        )

    if manual_handoff_requested:
        context = render_additional_context(
            state=SessionState.HANDOFF_PENDING,
            health_score=health_score,
            top_signals=top_signals,
        )
        return _build_decision(
            action=DecisionAction.PREPARE_HANDOFF,
            reason=DecisionReason.MANUAL_HANDOFF,
            state=SessionState.HANDOFF_PENDING,
            health_score=health_score,
            additional_context=context,
            should_prepare_handoff=True,
            handoff_reason="manual_handoff",
        )

    if state is SessionState.HANDOFF_PENDING:
        context = render_additional_context(
            state=SessionState.HANDOFF_PENDING,
            health_score=health_score,
            top_signals=top_signals,
        )
        notification = render_user_notification(
            state=SessionState.HANDOFF_PENDING,
            health_score=health_score,
            top_signals=top_signals,
        )
        return _build_decision(
            action=DecisionAction.PREPARE_HANDOFF,
            reason=DecisionReason.HANDOFF_PENDING,
            state=state,
            health_score=health_score,
            additional_context=context,
            user_notification=notification,
            should_prepare_handoff=True,
            handoff_reason="state_handoff_pending",
        )

    if at_stop_hook and state is SessionState.CRITICAL:
        context = render_additional_context(
            state=SessionState.HANDOFF_PENDING,
            health_score=health_score,
            top_signals=top_signals,
        )
        notification = render_user_notification(
            state=SessionState.HANDOFF_PENDING,
            health_score=health_score,
            top_signals=top_signals,
        )
        return _build_decision(
            action=DecisionAction.PREPARE_HANDOFF,
            reason=DecisionReason.STOP_HOOK_CRITICAL,
            state=state,
            health_score=health_score,
            additional_context=context,
            user_notification=notification,
            should_prepare_handoff=True,
            handoff_reason="critical_at_stop_hook",
        )

    if state is SessionState.HANDED_OFF:
        return _build_decision(
            action=DecisionAction.SILENT,
            reason=DecisionReason.HANDED_OFF,
            state=state,
            health_score=health_score,
        )

    if state is SessionState.HEALTHY:
        return _build_decision(
            action=DecisionAction.SILENT,
            reason=DecisionReason.HEALTHY,
            state=state,
            health_score=health_score,
        )

    if state is SessionState.WATCHING:
        return _build_decision(
            action=DecisionAction.OBSERVE,
            reason=DecisionReason.WATCHING,
            state=state,
            health_score=health_score,
        )

    if cooldown_active and state in {SessionState.DEGRADING, SessionState.CRITICAL}:
        return _build_decision(
            action=DecisionAction.COOLDOWN,
            reason=DecisionReason.WARNING_COOLDOWN,
            state=state,
            health_score=health_score,
            cooldown_active=True,
        )

    if state is SessionState.DEGRADING:
        context = render_additional_context(
            state=state,
            health_score=health_score,
            top_signals=top_signals,
        )
        return _build_decision(
            action=DecisionAction.INJECT_CONTEXT,
            reason=DecisionReason.DEGRADING,
            state=state,
            health_score=health_score,
            additional_context=context,
        )

    if state is SessionState.CRITICAL:
        context = render_additional_context(
            state=state,
            health_score=health_score,
            top_signals=top_signals,
        )
        notification = render_user_notification(
            state=state,
            health_score=health_score,
            top_signals=top_signals,
        )
        return _build_decision(
            action=DecisionAction.NOTIFY_USER,
            reason=DecisionReason.CRITICAL,
            state=state,
            health_score=health_score,
            additional_context=context,
            user_notification=notification,
        )

    return _build_decision(
        action=DecisionAction.SILENT,
        reason=DecisionReason.HEALTHY,
        state=state,
        health_score=health_score,
    )


def decision_summary(decision: DecisionResult) -> dict[str, object]:
    """Return a serialisable decision summary for smoke tests and future CLI output."""

    return {
        "action": decision.action.value,
        "reason": decision.reason.value,
        "state": decision.state.value,
        "health_score": round(decision.health_score, 4),
        "should_inject_context": decision.should_inject_context,
        "should_notify_user": decision.should_notify_user,
        "should_prepare_handoff": decision.should_prepare_handoff,
        "cooldown_active": decision.cooldown_active,
        "handoff_reason": decision.handoff_reason,
        "explanation": decision.explanation,
    }
