"""Session state machine for Pilot.

Day 37 added deterministic session-state transitions.

Day 38 adds hysteresis and anti-flapping behavior on top of that stable
contract. The deterministic API is kept for backwards compatibility, while the
new hysteresis API should be used by decision-layer code that evaluates health
repeatedly near state boundaries.

State model:
- healthy
- watching
- degrading
- critical
- handoff_pending
- handed_off
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pilot_core.constants import Defaults, SessionState, should_prepare_handoff
from pilot_core.health import HealthComputation, clamp_score


class StateTransitionReason(str, Enum):
    """Reason category for a session state transition."""

    HEALTH_BAND = "health_band"
    ESCALATION = "escalation"
    RECOVERY = "recovery"
    HANDOFF_REQUESTED = "handoff_requested"
    HANDOFF_COMPLETED = "handoff_completed"
    TERMINAL = "terminal"
    FORCED = "forced"


@dataclass(frozen=True)
class SessionStateSnapshot:
    """Current session state information used as state-machine input."""

    state: SessionState
    health_score: float
    turn_index: int | None = None
    fired_count: int = 0


@dataclass(frozen=True)
class StateTransition:
    """Result returned by the state machine."""

    previous_state: SessionState
    next_state: SessionState
    health_score: float
    reason: StateTransitionReason
    changed: bool
    should_prepare_handoff: bool
    explanation: str

    @property
    def is_terminal(self) -> bool:
        """Return True when the next state is the terminal handed-off state."""

        return self.next_state is SessionState.HANDED_OFF

    @property
    def is_escalation(self) -> bool:
        """Return True when this transition moves into a more severe state."""

        return state_rank(self.next_state) > state_rank(self.previous_state)

    @property
    def is_recovery(self) -> bool:
        """Return True when this transition moves into a less severe state."""

        return state_rank(self.next_state) < state_rank(self.previous_state)


STATE_RANKS: dict[SessionState, int] = {
    SessionState.HEALTHY: 0,
    SessionState.WATCHING: 1,
    SessionState.DEGRADING: 2,
    SessionState.CRITICAL: 3,
    SessionState.HANDOFF_PENDING: 4,
    SessionState.HANDED_OFF: 5,
}


def state_rank(state: SessionState) -> int:
    """Return severity rank for a session state."""

    return STATE_RANKS[state]


def state_from_health_score(health_score: float) -> SessionState:
    """Map a clamped health score to Pilot's deterministic session state band."""

    score = clamp_score(health_score)

    if score >= Defaults.HEALTH_HEALTHY_MIN:
        return SessionState.HEALTHY

    if score >= Defaults.HEALTH_WATCHING_MIN:
        return SessionState.WATCHING

    if score >= Defaults.HEALTH_DEGRADING_MIN:
        return SessionState.DEGRADING

    return SessionState.CRITICAL


def _validate_hysteresis(hysteresis: float) -> float:
    """Validate and return a hysteresis buffer."""

    if hysteresis < 0:
        raise ValueError("hysteresis must be greater than or equal to 0")

    if hysteresis >= 0.20:
        raise ValueError("hysteresis must be less than 0.20")

    return hysteresis


def hysteresis_state_from_health_score(
    current_state: SessionState,
    health_score: float,
    *,
    hysteresis: float = Defaults.STATE_HYSTERESIS,
) -> SessionState:
    """Map health to state while preventing boundary flapping.

    Hysteresis should dampen small boundary noise, not hide a severe health
    collapse. If the deterministic target is more than one severity band away,
    Pilot jumps directly to that target state.
    """

    score = clamp_score(health_score)
    buffer = _validate_hysteresis(hysteresis)

    if current_state is SessionState.HANDOFF_PENDING:
        return SessionState.HANDOFF_PENDING

    if current_state is SessionState.HANDED_OFF:
        return SessionState.HANDED_OFF

    deterministic_target = state_from_health_score(score)
    rank_delta = abs(state_rank(deterministic_target) - state_rank(current_state))

    if rank_delta > 1:
        return deterministic_target

    if current_state is SessionState.HEALTHY:
        if score < Defaults.HEALTH_HEALTHY_MIN - buffer:
            return SessionState.WATCHING
        return SessionState.HEALTHY

    if current_state is SessionState.WATCHING:
        if score >= Defaults.HEALTH_HEALTHY_MIN + buffer:
            return SessionState.HEALTHY
        if score < Defaults.HEALTH_WATCHING_MIN - buffer:
            return SessionState.DEGRADING
        return SessionState.WATCHING

    if current_state is SessionState.DEGRADING:
        if score >= Defaults.HEALTH_WATCHING_MIN + buffer:
            return SessionState.WATCHING
        if score < Defaults.HEALTH_DEGRADING_MIN - buffer:
            return SessionState.CRITICAL
        return SessionState.DEGRADING

    if current_state is SessionState.CRITICAL:
        if score >= Defaults.HEALTH_DEGRADING_MIN + buffer:
            return SessionState.DEGRADING
        return SessionState.CRITICAL

    return deterministic_target


def transition_reason(
    previous_state: SessionState,
    next_state: SessionState,
    *,
    forced: bool = False,
    handoff_requested: bool = False,
    handoff_completed: bool = False,
) -> StateTransitionReason:
    """Classify why a transition happened."""

    if forced:
        return StateTransitionReason.FORCED

    if previous_state is SessionState.HANDED_OFF:
        return StateTransitionReason.TERMINAL

    if handoff_completed:
        return StateTransitionReason.HANDOFF_COMPLETED

    if handoff_requested:
        return StateTransitionReason.HANDOFF_REQUESTED

    previous_rank = state_rank(previous_state)
    next_rank = state_rank(next_state)

    if next_rank > previous_rank:
        return StateTransitionReason.ESCALATION

    if next_rank < previous_rank:
        return StateTransitionReason.RECOVERY

    return StateTransitionReason.HEALTH_BAND


def _build_transition(
    current_state: SessionState,
    *,
    next_state: SessionState,
    health_score: float,
    reason: StateTransitionReason,
    explanation_suffix: str = "",
) -> StateTransition:
    """Build a StateTransition object consistently."""

    changed = current_state is not next_state
    suffix = f" {explanation_suffix}" if explanation_suffix else ""
    explanation = (
        f"{current_state.value} -> {next_state.value} "
        f"at health={health_score:.2f} via {reason.value}{suffix}"
    )

    return StateTransition(
        previous_state=current_state,
        next_state=next_state,
        health_score=health_score,
        reason=reason,
        changed=changed,
        should_prepare_handoff=should_prepare_handoff(next_state),
        explanation=explanation,
    )


def transition_session_state(
    current_state: SessionState,
    *,
    health_score: float,
    handoff_requested: bool = False,
    handoff_completed: bool = False,
    forced_state: SessionState | None = None,
) -> StateTransition:
    """Transition from the current session state to the next deterministic state.

    Rules:
    - handed_off is terminal unless forced_state is supplied
    - handoff_completed always moves to handed_off
    - handoff_requested from degrading/critical moves to handoff_pending
    - handoff_pending remains pending until completed or forced
    - otherwise state follows the deterministic health-score band
    """

    score = clamp_score(health_score)

    if forced_state is not None:
        next_state = forced_state
        reason = transition_reason(current_state, next_state, forced=True)
    elif current_state is SessionState.HANDED_OFF:
        next_state = SessionState.HANDED_OFF
        reason = transition_reason(current_state, next_state)
    elif handoff_completed:
        next_state = SessionState.HANDED_OFF
        reason = transition_reason(
            current_state,
            next_state,
            handoff_completed=True,
        )
    elif current_state is SessionState.HANDOFF_PENDING:
        next_state = SessionState.HANDOFF_PENDING
        reason = StateTransitionReason.HANDOFF_REQUESTED
    elif handoff_requested and current_state in {
        SessionState.DEGRADING,
        SessionState.CRITICAL,
    }:
        next_state = SessionState.HANDOFF_PENDING
        reason = transition_reason(
            current_state,
            next_state,
            handoff_requested=True,
        )
    else:
        next_state = state_from_health_score(score)
        reason = transition_reason(current_state, next_state)

    return _build_transition(
        current_state,
        next_state=next_state,
        health_score=score,
        reason=reason,
    )


def transition_session_state_with_hysteresis(
    current_state: SessionState,
    *,
    health_score: float,
    hysteresis: float = Defaults.STATE_HYSTERESIS,
    handoff_requested: bool = False,
    handoff_completed: bool = False,
    forced_state: SessionState | None = None,
) -> StateTransition:
    """Transition using hysteresis to avoid state flapping near boundaries.

    This preserves the same terminal and handoff rules as the deterministic
    transition function, but uses hysteresis for normal health-band movement.
    """

    score = clamp_score(health_score)
    buffer = _validate_hysteresis(hysteresis)

    if forced_state is not None:
        next_state = forced_state
        reason = transition_reason(current_state, next_state, forced=True)
    elif current_state is SessionState.HANDED_OFF:
        next_state = SessionState.HANDED_OFF
        reason = transition_reason(current_state, next_state)
    elif handoff_completed:
        next_state = SessionState.HANDED_OFF
        reason = transition_reason(
            current_state,
            next_state,
            handoff_completed=True,
        )
    elif current_state is SessionState.HANDOFF_PENDING:
        next_state = SessionState.HANDOFF_PENDING
        reason = StateTransitionReason.HANDOFF_REQUESTED
    elif handoff_requested and current_state in {
        SessionState.DEGRADING,
        SessionState.CRITICAL,
    }:
        next_state = SessionState.HANDOFF_PENDING
        reason = transition_reason(
            current_state,
            next_state,
            handoff_requested=True,
        )
    else:
        next_state = hysteresis_state_from_health_score(
            current_state,
            score,
            hysteresis=buffer,
        )
        reason = transition_reason(current_state, next_state)

    return _build_transition(
        current_state,
        next_state=next_state,
        health_score=score,
        reason=reason,
        explanation_suffix=f"(hysteresis={buffer:.2f})",
    )


def transition_from_health(
    current_state: SessionState,
    health: HealthComputation,
    *,
    handoff_requested: bool = False,
    handoff_completed: bool = False,
    forced_state: SessionState | None = None,
) -> StateTransition:
    """Transition using a HealthComputation object."""

    return transition_session_state(
        current_state,
        health_score=health.health_score,
        handoff_requested=handoff_requested,
        handoff_completed=handoff_completed,
        forced_state=forced_state,
    )


def transition_from_health_with_hysteresis(
    current_state: SessionState,
    health: HealthComputation,
    *,
    hysteresis: float = Defaults.STATE_HYSTERESIS,
    handoff_requested: bool = False,
    handoff_completed: bool = False,
    forced_state: SessionState | None = None,
) -> StateTransition:
    """Transition using HealthComputation plus hysteresis."""

    return transition_session_state_with_hysteresis(
        current_state,
        health_score=health.health_score,
        hysteresis=hysteresis,
        handoff_requested=handoff_requested,
        handoff_completed=handoff_completed,
        forced_state=forced_state,
    )


def apply_hysteresis_sequence(
    initial_state: SessionState,
    health_scores: list[float] | tuple[float, ...],
    *,
    hysteresis: float = Defaults.STATE_HYSTERESIS,
) -> tuple[StateTransition, ...]:
    """Apply hysteresis transitions over a sequence of health scores."""

    state = initial_state
    transitions: list[StateTransition] = []

    for score in health_scores:
        transition = transition_session_state_with_hysteresis(
            state,
            health_score=score,
            hysteresis=hysteresis,
        )
        transitions.append(transition)
        state = transition.next_state

    return tuple(transitions)


def state_transition_summary(transition: StateTransition) -> dict[str, object]:
    """Return a JSON-serialisable state transition summary."""

    return {
        "previous_state": transition.previous_state.value,
        "next_state": transition.next_state.value,
        "health_score": round(transition.health_score, 4),
        "reason": transition.reason.value,
        "changed": transition.changed,
        "should_prepare_handoff": transition.should_prepare_handoff,
        "is_escalation": transition.is_escalation,
        "is_recovery": transition.is_recovery,
        "is_terminal": transition.is_terminal,
        "explanation": transition.explanation,
    }


def transition_sequence_summary(
    transitions: list[StateTransition] | tuple[StateTransition, ...],
) -> list[dict[str, object]]:
    """Return serialisable summaries for a transition sequence."""

    return [state_transition_summary(transition) for transition in transitions]


class SessionStateMachine:
    """Small stateful wrapper around Pilot state transitions.

    This preserves the Day 37 public API while Day 38 adds hysteresis helpers.
    """

    def __init__(self, initial_state: SessionState = SessionState.HEALTHY) -> None:
        self._state = initial_state

    @property
    def state(self) -> SessionState:
        """Return current state."""

        return self._state

    def transition(
        self,
        *,
        health_score: float,
        handoff_requested: bool = False,
        handoff_completed: bool = False,
        forced_state: SessionState | None = None,
    ) -> StateTransition:
        """Apply one deterministic transition and store the new state."""

        result = transition_session_state(
            self._state,
            health_score=health_score,
            handoff_requested=handoff_requested,
            handoff_completed=handoff_completed,
            forced_state=forced_state,
        )
        self._state = result.next_state
        return result

    def transition_with_hysteresis(
        self,
        *,
        health_score: float,
        hysteresis: float = Defaults.STATE_HYSTERESIS,
        handoff_requested: bool = False,
        handoff_completed: bool = False,
        forced_state: SessionState | None = None,
    ) -> StateTransition:
        """Apply one hysteresis-safe transition and store the new state."""

        result = transition_session_state_with_hysteresis(
            self._state,
            health_score=health_score,
            hysteresis=hysteresis,
            handoff_requested=handoff_requested,
            handoff_completed=handoff_completed,
            forced_state=forced_state,
        )
        self._state = result.next_state
        return result
