from __future__ import annotations

from pilot_core.constants import SessionState, SignalName
from pilot_core.render.session_view import (
    SessionDetail,
    SessionListItem,
    SessionSignalItem,
    SessionToolUseItem,
    normalise_session_detail,
    normalise_session_list_item,
    render_session_detail,
    render_session_list,
    session_detail_summary,
    session_list_summary,
)


def test_normalise_session_list_item_from_raw_dict() -> None:
    item = normalise_session_list_item(
        {
            "id": "session-1",
            "state": "degrading",
            "health_score": 0.52,
            "tool_call_count": 4,
            "signal_count": 2,
            "total_tokens": 1200,
        }
    )

    assert item.session_id == "session-1"
    assert item.state is SessionState.DEGRADING
    assert item.health_score == 0.52
    assert item.tool_call_count == 4


def test_render_session_list_empty() -> None:
    rendered = render_session_list([])

    assert "Pilot sessions" in rendered
    assert "No sessions found" in rendered


def test_render_session_list_contains_core_columns() -> None:
    rendered = render_session_list(
        [
            SessionListItem(
                session_id="session-1",
                state=SessionState.CRITICAL,
                health_score=0.21,
                started_at_ms=1_700_000_000_000,
                ended_at_ms=1_700_000_060_000,
                tool_call_count=7,
                signal_count=4,
                total_tokens=9000,
            )
        ]
    )

    assert "session-1" in rendered
    assert "critical" in rendered
    assert "0.21" in rendered
    assert "9000" in rendered


def test_render_session_detail_contains_signals_and_tools() -> None:
    detail = SessionDetail(
        session=SessionListItem(
            session_id="session-2",
            state=SessionState.DEGRADING,
            health_score=0.44,
            tool_call_count=1,
            signal_count=1,
            total_tokens=500,
        ),
        signals=(
            SessionSignalItem(
                signal_name=SignalName.ERROR_CASCADE,
                score=0.8,
                confidence=0.9,
                fired=True,
                explanation="Repeated failures",
            ),
        ),
        tools=(
            SessionToolUseItem(
                tool_name="Edit",
                success=False,
                total_tokens=500,
                error_text="Patch failed",
            ),
        ),
        handoff_path=".pilot/handoffs/session-2.md",
    )

    rendered = render_session_detail(detail)

    assert "Pilot session: session-2" in rendered
    assert "## Summary" in rendered
    assert "## Signals" in rendered
    assert "error_cascade" in rendered
    assert "## Tool Calls" in rendered
    assert "Patch failed" in rendered
    assert ".pilot/handoffs/session-2.md" in rendered


def test_session_summaries_are_serialisable() -> None:
    detail = normalise_session_detail(
        {"session_id": "session-3", "state": "healthy"},
        signals=[{"signal_name": "token_burn", "score": 0.1, "fired": False}],
        tools=[{"tool_name": "Read", "success": True, "total_tokens": 100}],
    )

    list_summary = session_list_summary((detail.session,))
    detail_summary = session_detail_summary(detail)

    assert list_summary["session_count"] == 1
    assert list_summary["open_count"] == 1
    assert detail_summary["session_id"] == "session-3"
    assert detail_summary["tool_call_count"] == 1
    assert detail_summary["signal_count"] == 1
