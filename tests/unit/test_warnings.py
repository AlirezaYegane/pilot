from __future__ import annotations

from pilot_core.constants import SessionState, SignalName
from pilot_core.decision_engine import DecisionAction, DecisionReason, DecisionResult
from pilot_core.warnings import (
    WarningChannel,
    render_claude_additional_context,
    render_hook_stdout_payload,
    render_user_stderr,
    render_warning,
    warning_summary,
)


def make_decision(
    *,
    action: DecisionAction,
    state: SessionState,
    health_score: float,
    additional_context: str | None = None,
    user_notification: str | None = None,
    should_prepare_handoff: bool = False,
) -> DecisionResult:
    return DecisionResult(
        action=action,
        reason=DecisionReason.DEGRADING,
        state=state,
        health_score=health_score,
        should_inject_context=additional_context is not None,
        additional_context=additional_context,
        should_notify_user=user_notification is not None,
        user_notification=user_notification,
        should_prepare_handoff=should_prepare_handoff,
        handoff_reason="test handoff" if should_prepare_handoff else None,
        cooldown_active=False,
        explanation="test decision",
    )


def test_silent_decision_renders_no_warning() -> None:
    decision = make_decision(
        action=DecisionAction.SILENT,
        state=SessionState.HEALTHY,
        health_score=0.95,
    )

    assert render_claude_additional_context(decision) is None
    assert render_user_stderr(decision) is None
    assert render_hook_stdout_payload(decision) == {}


def test_degrading_decision_renders_claude_context() -> None:
    decision = make_decision(
        action=DecisionAction.INJECT_CONTEXT,
        state=SessionState.DEGRADING,
        health_score=0.52,
        additional_context="Pause and summarize progress before another patch.",
    )

    text = render_claude_additional_context(
        decision,
        top_signals=(SignalName.ERROR_CASCADE, SignalName.REPEATED_CALLS),
    )

    assert text is not None
    assert "Pilot context" in text
    assert "health=0.52" in text
    assert "error_cascade" in text
    assert "Pause and summarize" in text


def test_critical_decision_renders_user_stderr() -> None:
    decision = make_decision(
        action=DecisionAction.NOTIFY_USER,
        state=SessionState.CRITICAL,
        health_score=0.21,
        additional_context="Critical context",
        user_notification="Critical user warning",
    )

    text = render_user_stderr(
        decision,
        top_signals=(SignalName.RATE_LIMIT,),
    )

    assert text is not None
    assert "Pilot warning" in text
    assert "health=0.21" in text
    assert "rate_limit" in text
    assert "Critical user warning" in text


def test_handoff_pending_renders_fallbacks() -> None:
    decision = make_decision(
        action=DecisionAction.PREPARE_HANDOFF,
        state=SessionState.HANDOFF_PENDING,
        health_score=0.18,
        should_prepare_handoff=True,
    )

    context = render_claude_additional_context(decision)
    stderr = render_user_stderr(decision)

    assert context is not None
    assert "handoff_pending" in context
    assert stderr is not None
    assert "handoff pending" in stderr.lower()


def test_hook_stdout_payload_uses_additional_context_key() -> None:
    decision = make_decision(
        action=DecisionAction.INJECT_CONTEXT,
        state=SessionState.DEGRADING,
        health_score=0.51,
        additional_context="Claude should self-correct.",
    )

    payload = render_hook_stdout_payload(decision)

    assert set(payload) == {"additionalContext"}
    assert "Claude should self-correct" in payload["additionalContext"]


def test_warning_text_can_be_bounded() -> None:
    decision = make_decision(
        action=DecisionAction.INJECT_CONTEXT,
        state=SessionState.DEGRADING,
        health_score=0.50,
        additional_context="x" * 2_000,
    )

    rendered = render_warning(
        decision,
        channel=WarningChannel.CLAUDE_CONTEXT,
        max_chars=100,
    )

    assert rendered is not None
    assert len(rendered.message) <= 100
    assert "[truncated]" in rendered.message


def test_warning_summary_is_serialisable() -> None:
    decision = make_decision(
        action=DecisionAction.INJECT_CONTEXT,
        state=SessionState.DEGRADING,
        health_score=0.49,
        additional_context="Summarize before continuing.",
    )

    summary = warning_summary(
        decision,
        top_signals=(SignalName.TOKEN_BURN, "custom_signal"),
    )

    assert summary["action"] == "inject_context"
    assert summary["state"] == "degrading"
    assert summary["has_additional_context"] is True
    assert summary["has_user_stderr"] is False
    assert summary["hook_payload_keys"] == ["additionalContext"]
    assert summary["top_signals"] == ["token_burn", "custom_signal"]
