from __future__ import annotations

from typing import Any

from pilot_core.constants import Severity, SignalName
from pilot_core.signals.repeated_calls import (
    evaluate_repeated_calls,
    fingerprint_tool_call,
    hash_tool_input,
    normalise_tool_input,
    repeated_call_score,
    repeated_call_severity,
    stable_tool_input_json,
)


def test_normalise_tool_input_sorts_dict_keys_recursively() -> None:
    left = {"b": 2, "a": {"z": " yes ", "x": 1}}
    right = {"a": {"x": 1, "z": "yes"}, "b": 2}

    assert normalise_tool_input(left) == normalise_tool_input(right)


def test_stable_tool_input_json_is_order_independent_for_dicts() -> None:
    left = {"command": "pytest", "timeout": 10}
    right = {"timeout": 10, "command": "pytest"}

    assert stable_tool_input_json(left) == stable_tool_input_json(right)


def test_hash_tool_input_is_stable_for_equivalent_payloads() -> None:
    left = {"command": " pytest ", "env": {"B": "2", "A": "1"}}
    right = {"env": {"A": "1", "B": "2"}, "command": "pytest"}

    assert hash_tool_input(left) == hash_tool_input(right)


def test_fingerprint_tool_call_includes_tool_name() -> None:
    bash = fingerprint_tool_call("Bash", {"command": "pytest"})
    read = fingerprint_tool_call("Read", {"command": "pytest"})

    assert bash.tool_name == "Bash"
    assert read.tool_name == "Read"
    assert bash.input_hash == read.input_hash
    assert bash != read


def test_repeated_call_score_shape() -> None:
    assert repeated_call_score(0) == 0.0
    assert repeated_call_score(1) == 0.0
    assert repeated_call_score(2) == 0.35
    assert repeated_call_score(3) == 0.65
    assert repeated_call_score(4) == 0.80
    assert repeated_call_score(10) == 1.0


def test_repeated_call_severity_mapping() -> None:
    assert repeated_call_severity(0.0) is Severity.INFO
    assert repeated_call_severity(0.35) is Severity.INFO
    assert repeated_call_severity(0.65) is Severity.WARNING
    assert repeated_call_severity(0.95) is Severity.CRITICAL


def test_evaluate_repeated_calls_returns_empty_result_without_calls() -> None:
    result = evaluate_repeated_calls([])

    assert result.signal_name is SignalName.REPEATED_CALLS
    assert result.score == 0.0
    assert result.confidence == 0.0
    assert result.repeat_count == 0
    assert result.repeated_fingerprint is None
    assert "No recent tool calls" in result.explanation


def test_evaluate_repeated_calls_detects_three_identical_calls() -> None:
    calls = [
        {"tool_name": "Bash", "tool_input": {"command": "pytest"}},
        {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        {"tool_name": "Bash", "tool_input": {"command": " pytest "}},
        {"tool_name": "Bash", "tool_input": {"command": "pytest"}},
    ]

    result = evaluate_repeated_calls(calls)

    assert result.signal_name is SignalName.REPEATED_CALLS
    assert result.score == 0.65
    assert result.severity is Severity.WARNING
    assert result.repeat_count == 3
    assert result.repeated_fingerprint is not None
    assert result.repeated_fingerprint.tool_name == "Bash"
    assert "Bash was called 3 times" in result.explanation


def test_evaluate_repeated_calls_uses_recent_window_only() -> None:
    old_repeated = [{"tool_name": "Bash", "tool_input": {"command": "old"}} for _ in range(5)]
    recent_mixed = [
        {"tool_name": "Bash", "tool_input": {"command": "new-1"}},
        {"tool_name": "Bash", "tool_input": {"command": "new-2"}},
        {"tool_name": "Bash", "tool_input": {"command": "new-3"}},
    ]

    result = evaluate_repeated_calls(old_repeated + recent_mixed, window_size=3)

    assert result.score == 0.0
    assert result.repeat_count == 1
    assert result.repeated_fingerprint is None


def test_evaluate_repeated_calls_ignores_items_without_tool_name() -> None:
    calls: list[dict[str, Any]] = [
        {"tool_input": {"command": "pytest"}},
        {"tool_name": "", "tool_input": {"command": "pytest"}},
    ]

    result = evaluate_repeated_calls(calls)

    assert result.score == 0.0
    assert result.repeat_count == 0
    assert result.repeated_fingerprint is None
