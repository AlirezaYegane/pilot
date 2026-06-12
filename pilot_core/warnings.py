"""Warning renderers for Pilot decisions.

Day 40 converts pure decision-engine results into hook-safe text outputs.

This module does not decide policy. It only renders:

- Claude-facing additionalContext text
- user-facing stderr text
- hook stdout payloads such as {"additionalContext": "..."}

The renderers are intentionally side-effect free. They do not print, write to
storage, or call hooks directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from pilot_core.constants import SessionState, SignalName
from pilot_core.decision_engine import DecisionAction, DecisionResult

DEFAULT_MAX_CLAUDE_CONTEXT_CHARS = 1_200
DEFAULT_MAX_USER_STDERR_CHARS = 700


class WarningChannel(str, Enum):
    """Where a rendered warning is meant to be used."""

    CLAUDE_CONTEXT = "claude_context"
    USER_STDERR = "user_stderr"


@dataclass(frozen=True)
class RenderedWarning:
    """Rendered warning text with metadata for hooks and tests."""

    channel: WarningChannel
    state: SessionState
    health_score: float
    title: str
    message: str
    top_signals: tuple[str, ...]
    action: DecisionAction

    @property
    def text(self) -> str:
        """Return the final formatted warning text."""

        lines = [self.title, self.message]

        if self.top_signals:
            lines.append(f"Signals: {', '.join(self.top_signals)}")

        lines.append(f"Action: {self.action.value}")
        return "\n".join(lines)


def clamp_health(value: float) -> float:
    """Clamp a health score into the 0..1 range."""

    return max(0.0, min(1.0, value))


def _signal_values(signals: Sequence[SignalName | str]) -> tuple[str, ...]:
    """Return stable signal string values."""

    values: list[str] = []

    for signal in signals:
        if isinstance(signal, SignalName):
            values.append(signal.value)
        else:
            text = str(signal).strip()
            if text:
                values.append(text)

    return tuple(values)


def _bounded_text(text: str, *, max_chars: int) -> str:
    """Return bounded text without raising on small limits."""

    if max_chars <= 0:
        return ""

    if len(text) <= max_chars:
        return text

    suffix = "... [truncated]"
    keep = max(0, max_chars - len(suffix))
    return f"{text[:keep]}{suffix}"


def _warning_title(*, channel: WarningChannel, state: SessionState, health_score: float) -> str:
    """Return a compact warning title."""

    health = clamp_health(health_score)

    if channel is WarningChannel.CLAUDE_CONTEXT:
        if state is SessionState.DEGRADING:
            return f"Pilot context: session degrading, health={health:.2f}"
        if state is SessionState.CRITICAL:
            return f"Pilot context: session critical, health={health:.2f}"
        if state is SessionState.HANDOFF_PENDING:
            return f"Pilot context: handoff pending, health={health:.2f}"
        return f"Pilot context: state={state.value}, health={health:.2f}"

    if state is SessionState.CRITICAL:
        return f"Pilot warning: critical session, health={health:.2f}"
    if state is SessionState.HANDOFF_PENDING:
        return f"Pilot warning: handoff pending, health={health:.2f}"
    if state is SessionState.DEGRADING:
        return f"Pilot warning: session degrading, health={health:.2f}"
    return f"Pilot notice: state={state.value}, health={health:.2f}"


def _fallback_claude_message(decision: DecisionResult) -> str:
    """Return Claude-facing fallback text when decision has no explicit context."""

    if decision.state is SessionState.DEGRADING:
        return (
            "Pilot detected signs of session degradation. Before continuing, "
            "summarize progress, identify the current blocker, and avoid repeating "
            "failed tool calls."
        )

    if decision.state is SessionState.CRITICAL:
        return (
            "Pilot detected critical session degradation. Stop expanding the solution "
            "blindly, summarize the current state, identify the failing loop, and "
            "prepare for a clean handoff if needed."
        )

    if decision.state is SessionState.HANDOFF_PENDING:
        return (
            "Pilot marked this session as handoff_pending. Prepare a concise handoff "
            "summary with progress, modified files, blockers, next steps, and what "
            "not to redo."
        )

    return ""


def _fallback_user_message(decision: DecisionResult) -> str:
    """Return user-facing fallback text when decision has no explicit notification."""

    if decision.state is SessionState.CRITICAL:
        return (
            "Pilot warning: this session looks critical. Consider stopping soon and "
            "creating a clean handoff."
        )

    if decision.state is SessionState.HANDOFF_PENDING:
        return "Pilot handoff pending: summarize the current session before continuing."

    if decision.state is SessionState.DEGRADING:
        return "Pilot notice: this session is showing degradation signals. Continue with care."

    return ""


def render_warning(
    decision: DecisionResult,
    *,
    channel: WarningChannel,
    top_signals: Sequence[SignalName | str] = tuple(),
    max_chars: int,
) -> RenderedWarning | None:
    """Render a decision into a channel-specific warning.

    Silent, observe, and cooldown decisions do not render warnings.
    """

    if decision.action in {
        DecisionAction.SILENT,
        DecisionAction.OBSERVE,
        DecisionAction.COOLDOWN,
    }:
        return None

    if channel is WarningChannel.CLAUDE_CONTEXT:
        if not decision.should_inject_context and not decision.should_prepare_handoff:
            return None

        message = decision.additional_context or _fallback_claude_message(decision)
    else:
        if not decision.should_notify_user and not decision.should_prepare_handoff:
            return None

        message = decision.user_notification or _fallback_user_message(decision)

    if not message.strip():
        return None

    rendered = RenderedWarning(
        channel=channel,
        state=decision.state,
        health_score=clamp_health(decision.health_score),
        title=_warning_title(
            channel=channel,
            state=decision.state,
            health_score=decision.health_score,
        ),
        message=_bounded_text(message.strip(), max_chars=max_chars),
        top_signals=_signal_values(top_signals),
        action=decision.action,
    )

    return rendered


def render_claude_additional_context(
    decision: DecisionResult,
    *,
    top_signals: Sequence[SignalName | str] = tuple(),
    max_chars: int = DEFAULT_MAX_CLAUDE_CONTEXT_CHARS,
) -> str | None:
    """Return Claude-facing additionalContext text, or None when silent."""

    rendered = render_warning(
        decision,
        channel=WarningChannel.CLAUDE_CONTEXT,
        top_signals=top_signals,
        max_chars=max_chars,
    )

    return rendered.text if rendered is not None else None


def render_user_stderr(
    decision: DecisionResult,
    *,
    top_signals: Sequence[SignalName | str] = tuple(),
    max_chars: int = DEFAULT_MAX_USER_STDERR_CHARS,
) -> str | None:
    """Return user-facing stderr text, or None when silent."""

    rendered = render_warning(
        decision,
        channel=WarningChannel.USER_STDERR,
        top_signals=top_signals,
        max_chars=max_chars,
    )

    return rendered.text if rendered is not None else None


def render_hook_stdout_payload(
    decision: DecisionResult,
    *,
    top_signals: Sequence[SignalName | str] = tuple(),
    max_chars: int = DEFAULT_MAX_CLAUDE_CONTEXT_CHARS,
) -> dict[str, str]:
    """Return hook stdout payload for Claude Code.

    Claude Code hook integration expects stdout JSON such as:

    {"additionalContext": "..."}
    """

    additional_context = render_claude_additional_context(
        decision,
        top_signals=top_signals,
        max_chars=max_chars,
    )

    if additional_context is None:
        return {}

    return {"additionalContext": additional_context}


def warning_summary(
    decision: DecisionResult,
    *,
    top_signals: Sequence[SignalName | str] = tuple(),
) -> dict[str, object]:
    """Return a serialisable summary for smoke scripts and CLI output."""

    additional_context = render_claude_additional_context(
        decision,
        top_signals=top_signals,
    )
    user_stderr = render_user_stderr(
        decision,
        top_signals=top_signals,
    )

    return {
        "action": decision.action.value,
        "state": decision.state.value,
        "health_score": round(clamp_health(decision.health_score), 4),
        "has_additional_context": additional_context is not None,
        "has_user_stderr": user_stderr is not None,
        "hook_payload_keys": sorted(render_hook_stdout_payload(decision).keys()),
        "top_signals": list(_signal_values(top_signals)),
    }
