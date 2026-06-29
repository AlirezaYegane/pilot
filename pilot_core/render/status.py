"""Terminal renderer for Pilot status snapshots.

Day 52 renders:
- health bar
- state view
- signal list

This module has no terminal side effects. It returns strings only.
"""

from __future__ import annotations

from pilot_core.constants import SessionState
from pilot_core.status import PilotStatusSnapshot, SignalStatus

DEFAULT_HEALTH_BAR_WIDTH = 24


def clamp_health(value: float) -> float:
    """Clamp health into 0..1."""

    return max(0.0, min(1.0, value))


def render_health_bar(
    health_score: float,
    *,
    width: int = DEFAULT_HEALTH_BAR_WIDTH,
) -> str:
    """Render an ASCII health bar."""

    if width < 4:
        raise ValueError("width must be at least 4")

    score = clamp_health(health_score)
    filled = round(score * width)
    empty = width - filled

    return f"[{'#' * filled}{'-' * empty}] {score * 100:5.1f}%"


def state_label(state: SessionState) -> str:
    """Return a readable state label."""

    return state.value.replace("_", " ")


def render_state_view(snapshot: PilotStatusSnapshot) -> str:
    """Render the current-to-next state transition."""

    transition = snapshot.transition
    arrow = "->" if transition.changed else "="

    return (
        f"State: {state_label(transition.previous_state)} "
        f"{arrow} {state_label(transition.next_state)} "
        f"({transition.reason.value})"
    )


def _signal_flag(signal: SignalStatus) -> str:
    """Return compact fired/quiet marker."""

    return "FIRED" if signal.fired else "quiet"


def render_signal_line(signal: SignalStatus) -> str:
    """Render one signal row."""

    explanation = signal.explanation.strip()
    suffix = f" - {explanation}" if explanation else ""

    return (
        f"- {signal.signal_name.value}: "
        f"score={signal.score:.2f} "
        f"confidence={signal.confidence:.2f} "
        f"{_signal_flag(signal)}"
        f"{suffix}"
    )


def render_signal_list(
    signals: tuple[SignalStatus, ...],
    *,
    max_signals: int = 8,
) -> str:
    """Render ordered signal rows."""

    if max_signals < 1:
        raise ValueError("max_signals must be at least 1")

    ordered = tuple(
        sorted(
            signals,
            key=lambda signal: (
                signal.fired,
                signal.score,
                signal.confidence,
                signal.signal_name.value,
            ),
            reverse=True,
        )
    )

    visible = ordered[:max_signals]
    hidden_count = max(0, len(ordered) - len(visible))

    lines = ["Signals:"]

    if not visible:
        lines.append("- none")
    else:
        lines.extend(render_signal_line(signal) for signal in visible)

    if hidden_count:
        lines.append(f"- ... {hidden_count} more")

    return "\n".join(lines)


def render_status_snapshot(
    snapshot: PilotStatusSnapshot,
    *,
    max_signals: int = 8,
) -> str:
    """Render a full Pilot status snapshot."""

    session_text = snapshot.session_id if snapshot.session_id is not None else "unknown"

    lines = [
        "Pilot Status",
        f"Session: {session_text}",
        f"Source: {snapshot.source}",
        f"Health: {render_health_bar(snapshot.health_score)}",
        render_state_view(snapshot),
        f"Fired signals: {snapshot.fired_count}/{len(snapshot.signals)}",
        "",
        render_signal_list(snapshot.signals, max_signals=max_signals),
    ]

    return "\n".join(lines).rstrip() + "\n"
