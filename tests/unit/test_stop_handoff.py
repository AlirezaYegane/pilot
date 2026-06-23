from __future__ import annotations

from pathlib import Path

from pilot_core.constants import ActivationMode, SignalName
from pilot_core.stop_handoff import (
    build_stop_handoff_result,
    generate_stop_handoff_from_payload,
    stop_handoff_summary,
)


def critical_signal_results() -> list[dict[str, object]]:
    return [
        {
            "signal_name": signal.value,
            "score": 1.0,
            "confidence": 1.0,
            "fired": True,
        }
        for signal in SignalName
    ]


def failing_records() -> list[dict[str, object]]:
    return [
        {
            "event_id": f"fail-{index}",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest tests/unit/test_loop.py"},
            "input_hash": "same-pytest-command",
            "success": False,
            "error": {"message": "same pytest failure"},
            "turn_index": index,
            "file_path": "pilot_core/example.py",
        }
        for index in range(4)
    ]


def test_action_mode_generates_handoff_markdown() -> None:
    result = build_stop_handoff_result(
        critical_signal_results(),
        records=failing_records(),
        session_id="unit-day47",
        task="Finish stop hook handoff integration",
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
        generated_at="2026-06-23T00:00:00+00:00",
    )

    assert result.should_generate_handoff
    assert result.handoff is not None
    assert result.markdown is not None
    assert "# Pilot Handoff" in result.markdown
    assert "## Blockers" in result.markdown
    assert "## Do Not Redo" in result.markdown
    assert result.reason == "handoff_generated"


def test_shadow_mode_suppresses_visible_handoff() -> None:
    result = build_stop_handoff_result(
        critical_signal_results(),
        records=failing_records(),
        session_id="unit-shadow",
        default_mode=ActivationMode.SHADOW,
        at_stop_hook=True,
    )

    assert not result.should_generate_handoff
    assert result.handoff is None
    assert result.markdown is None
    assert result.reason == "policy_did_not_request_handoff"


def test_warn_mode_suppresses_handoff_artifact() -> None:
    result = build_stop_handoff_result(
        critical_signal_results(),
        records=failing_records(),
        session_id="unit-warn",
        default_mode=ActivationMode.WARN,
        at_stop_hook=True,
    )

    assert not result.should_generate_handoff
    assert result.handoff is None
    assert result.markdown is None
    assert result.reason in {
        "policy_did_not_request_handoff",
        "handoff_suppressed_by_warn_mode",
    }


def test_write_files_creates_markdown_and_json(tmp_path: Path) -> None:
    result = build_stop_handoff_result(
        critical_signal_results(),
        records=failing_records(),
        session_id="unit-write",
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
        handoff_dir=tmp_path,
        write_files=True,
        generated_at="2026-06-23T00:00:00+00:00",
    )

    assert result.markdown_path is not None
    assert result.json_path is not None
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.markdown_path.read_text(encoding="utf-8").startswith("# Pilot Handoff")
    assert '"task"' in result.json_path.read_text(encoding="utf-8")


def test_payload_adapter_generates_handoff(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "session_id": "payload-day47",
        "task": "Payload adapter test",
        "records": failing_records(),
        "signal_results": critical_signal_results(),
        "handoff_dir": str(tmp_path),
        "write_files": True,
        "default_mode": "action",
    }

    result = generate_stop_handoff_from_payload(payload)

    assert result.should_generate_handoff
    assert result.markdown_path is not None
    assert result.markdown_path.exists()


def test_stop_handoff_summary_is_serialisable() -> None:
    result = build_stop_handoff_result(
        critical_signal_results(),
        records=failing_records(),
        session_id="unit-summary",
        default_mode=ActivationMode.ACTION,
        at_stop_hook=True,
    )

    summary = stop_handoff_summary(result)

    assert summary["should_generate_handoff"] is True
    assert summary["effective_mode"] == "action"
    assert summary["policy_action"] == "prepare_handoff"
    assert summary["markdown_summary"] is not None
