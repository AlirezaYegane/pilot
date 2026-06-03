from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, cast

from pilot_core.constants import SignalName
from pilot_core.signals.context_saturation import evaluate_context_saturation
from pilot_core.signals.error_cascade import evaluate_error_cascade
from pilot_core.signals.token_burn import evaluate_token_burn

RawRecord = Mapping[str, object]
SignalEvaluator = Callable[[Sequence[RawRecord]], object]


class ContractSignalResult(Protocol):
    signal_name: SignalName
    score: float
    confidence: float
    explanation: str


def _evaluate_repeated_calls(records: Sequence[RawRecord]) -> object:
    module = importlib.import_module("pilot_core.signals.repeated_calls")
    evaluator = getattr(module, "evaluate_repeated_calls", None)

    assert callable(
        evaluator
    ), "pilot_core.signals.repeated_calls must expose evaluate_repeated_calls"

    return cast(SignalEvaluator, evaluator)(records)


def _assert_signal_result_contract(result: object, expected_name: SignalName) -> None:
    typed_result = cast(ContractSignalResult, result)

    assert typed_result.signal_name is expected_name
    assert 0.0 <= float(typed_result.score) <= 1.0
    assert 0.0 <= float(typed_result.confidence) <= 1.0
    assert typed_result.explanation.strip()

    if hasattr(result, "fired"):
        fired = result.fired
        assert isinstance(fired, bool)


def test_four_signal_results_follow_common_contract() -> None:
    repeated_result = _evaluate_repeated_calls(
        [
            {
                "tool_name": "Bash",
                "tool_input": {"command": "pytest"},
                "input_payload": {"command": "pytest"},
                "input_hash": "same",
            },
            {
                "tool_name": "Bash",
                "tool_input": {"command": "pytest"},
                "input_payload": {"command": "pytest"},
                "input_hash": "same",
            },
            {
                "tool_name": "Bash",
                "tool_input": {"command": "pytest"},
                "input_payload": {"command": "pytest"},
                "input_hash": "same",
            },
        ]
    )

    error_result = evaluate_error_cascade(
        cast(
            list[object],
            [
                {"success": True},
                {"success": False},
                {"success": False},
                {"success": True},
                {"success": False},
            ],
        )
    )

    token_result = evaluate_token_burn(
        [
            *({"turn_index": index, "total_tokens": 100} for index in range(10)),
            {"turn_index": 10, "total_tokens": 250},
            {"turn_index": 11, "total_tokens": 260},
            {"turn_index": 12, "total_tokens": 240},
        ]
    )

    context_result = evaluate_context_saturation(
        [{"total_tokens": 150_000}],
        model_context_limit=200_000,
        system_prompt_token_offset=20_000,
    )

    _assert_signal_result_contract(repeated_result, SignalName.REPEATED_CALLS)
    _assert_signal_result_contract(error_result, SignalName.ERROR_CASCADE)
    _assert_signal_result_contract(token_result, SignalName.TOKEN_BURN)
    _assert_signal_result_contract(context_result, SignalName.CONTEXT_SATURATION)


def test_empty_input_does_not_break_supported_signals() -> None:
    cases = [
        (evaluate_error_cascade([]), SignalName.ERROR_CASCADE),
        (evaluate_token_burn([]), SignalName.TOKEN_BURN),
        (evaluate_context_saturation([]), SignalName.CONTEXT_SATURATION),
    ]

    for result, expected_name in cases:
        _assert_signal_result_contract(result, expected_name)
        typed_result = cast(ContractSignalResult, result)
        assert typed_result.score == 0.0
        assert typed_result.confidence <= 1.0


def test_repeated_calls_handles_minimal_missing_payload_without_crashing() -> None:
    result = _evaluate_repeated_calls(
        [
            {},
            {"tool_name": "Bash"},
            {"tool_input": {"command": "pytest"}},
        ]
    )

    _assert_signal_result_contract(result, SignalName.REPEATED_CALLS)


def test_error_cascade_boundary_equal_threshold_does_not_fire() -> None:
    result = evaluate_error_cascade(
        cast(
            list[object],
            [
                {"success": True},
                {"success": False},
                {"success": False},
                {"success": True},
                {"success": True},
            ],
        )
    )

    assert result.failure_rate == 0.4
    assert result.score == 1.0
    assert not result.fired


def test_token_burn_boundary_equal_threshold_does_not_fire() -> None:
    result = evaluate_token_burn(
        [
            *({"turn_index": index, "total_tokens": 100} for index in range(10)),
            {"turn_index": 10, "total_tokens": 200},
            {"turn_index": 11, "total_tokens": 200},
            {"turn_index": 12, "total_tokens": 200},
        ]
    )

    assert result.ratio == 2.0
    assert not result.fired


def test_context_saturation_boundary_equal_threshold_does_not_fire() -> None:
    result = evaluate_context_saturation(
        [{"total_tokens": 140_000}],
        model_context_limit=200_000,
        system_prompt_token_offset=20_000,
    )

    assert result.saturation_ratio == 0.8
    assert not result.fired


def test_bad_numeric_payloads_are_safe_for_token_and_context_signals() -> None:
    token_result = evaluate_token_burn(
        [
            {"turn_index": "bad", "total_tokens": "bad"},
            {"turn_index": 1, "input_tokens": None, "output_tokens": object()},
        ]
    )
    context_result = evaluate_context_saturation(
        [
            {"total_tokens": "bad"},
            {"input_tokens": None, "output_tokens": object()},
        ]
    )

    _assert_signal_result_contract(token_result, SignalName.TOKEN_BURN)
    _assert_signal_result_contract(context_result, SignalName.CONTEXT_SATURATION)
