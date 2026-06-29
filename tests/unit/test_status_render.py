from __future__ import annotations

from pilot_core.constants import SessionState, SignalName
from pilot_core.render.status import (
    render_health_bar,
    render_signal_line,
    render_status_snapshot,
)
from pilot_core.status import (
    SignalStatus,
    build_empty_status_snapshot,
    build_status_snapshot,
    normalise_signal_statuses,
    status_snapshot_summary,
)


def test_render_health_bar_bounds_score() -> None:
    assert render_health_bar(2.0, width=10) == "[##########] 100.0%"
    assert render_health_bar(-1.0, width=10) == "[----------]   0.0%"


def test_render_signal_line_marks_fired_signal() -> None:
    signal = SignalStatus(
        signal_name=SignalName.ERROR_CASCADE,
        score=0.9,
        confidence=1.0,
        fired=True,
        explanation="failure rate is high",
    )

    line = render_signal_line(signal)

    assert "error_cascade" in line
    assert "FIRED" in line
    assert "failure rate is high" in line


def test_normalise_signal_statuses_from_mapping() -> None:
    rows = normalise_signal_statuses(
        {
            SignalName.TOKEN_BURN: {
                "signal_name": SignalName.TOKEN_BURN,
                "score": 0.75,
                "confidence": 0.8,
                "fired": True,
                "explanation": "recent usage is high",
            }
        }
    )

    assert len(rows) == 1
    assert rows[0].signal_name is SignalName.TOKEN_BURN
    assert rows[0].fired is True


def test_build_status_snapshot_from_signal_results() -> None:
    snapshot = build_status_snapshot(
        {
            SignalName.ERROR_CASCADE: {
                "signal_name": SignalName.ERROR_CASCADE,
                "score": 1.0,
                "confidence": 1.0,
                "fired": True,
                "explanation": "errors are cascading",
            },
            SignalName.TOKEN_BURN: {
                "signal_name": SignalName.TOKEN_BURN,
                "score": 0.0,
                "confidence": 1.0,
                "fired": False,
                "explanation": "quiet",
            },
        },
        current_state=SessionState.HEALTHY,
        session_id="unit-status",
    )

    assert snapshot.session_id == "unit-status"
    assert snapshot.fired_count == 1
    assert snapshot.health_score < 1.0


def test_empty_status_snapshot_is_quiet_and_renderable() -> None:
    snapshot = build_empty_status_snapshot(session_id="empty-status")
    text = render_status_snapshot(snapshot)

    assert snapshot.fired_count == 0
    assert "Pilot Status" in text
    assert "Health:" in text
    assert "Signals:" in text


def test_status_snapshot_summary_is_serialisable() -> None:
    snapshot = build_empty_status_snapshot(session_id="summary-status")
    summary = status_snapshot_summary(snapshot)

    assert summary["session_id"] == "summary-status"
    assert summary["current_state"] == "healthy"
    assert summary["fired_count"] == 0
    assert isinstance(summary["signals"], list)
