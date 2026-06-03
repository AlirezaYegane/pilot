from __future__ import annotations

from pilot_core.constants import SignalName
from pilot_core.signals.v1 import evaluate_signal_engine_v1


def test_evaluate_signal_engine_v1_returns_stable_result_bundle() -> None:
    records = [
        {"tool_name": "Bash", "input_hash": "same", "success": True, "total_tokens": 100},
        {"tool_name": "Bash", "input_hash": "same", "success": False, "total_tokens": 100},
        {"tool_name": "Bash", "input_hash": "same", "success": False, "total_tokens": 100},
        {"tool_name": "Read", "input_hash": "other", "success": False, "total_tokens": 170_000},
    ]

    result = evaluate_signal_engine_v1(records)

    assert len(result.results) == 4
    assert result.max_score >= 0.0
    assert result.fired_count >= 1

    assert set(result.as_score_map()) == {
        SignalName.REPEATED_CALLS.value,
        SignalName.ERROR_CASCADE.value,
        SignalName.TOKEN_BURN.value,
        SignalName.CONTEXT_SATURATION.value,
    }


def test_signal_engine_v1_score_map_is_serialisable() -> None:
    result = evaluate_signal_engine_v1(
        [
            {"tool_name": "Read", "input_hash": "a", "success": True, "total_tokens": 100},
            {"tool_name": "Edit", "input_hash": "b", "success": True, "total_tokens": 100},
            {"tool_name": "Bash", "input_hash": "c", "success": True, "total_tokens": 100},
        ]
    )

    score_map = result.as_score_map()

    assert all(isinstance(key, str) for key in score_map)
    assert all(isinstance(value, float) for value in score_map.values())
