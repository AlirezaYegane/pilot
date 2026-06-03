from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from pilot_core.constants import SignalName
from pilot_core.signals.context_saturation import evaluate_context_saturation
from pilot_core.signals.error_cascade import evaluate_error_cascade
from pilot_core.signals.token_burn import evaluate_token_burn

RawRecord = Mapping[str, object]
SignalEvaluator = Callable[[Sequence[RawRecord]], object]


class ReplaySignalResult(Protocol):
    signal_name: SignalName
    score: float
    confidence: float
    explanation: str


FIXTURE_DIR = Path("tests") / "fixtures"


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        assert isinstance(raw, dict)
        records.append(cast(dict[str, object], raw))

    return records


def _evaluate_repeated_calls(records: Sequence[RawRecord]) -> object:
    module = importlib.import_module("pilot_core.signals.repeated_calls")
    evaluator = getattr(module, "evaluate_repeated_calls", None)

    assert callable(
        evaluator
    ), "pilot_core.signals.repeated_calls must expose evaluate_repeated_calls"

    return cast(SignalEvaluator, evaluator)(records)


def _assert_replay_result(
    result: object,
    *,
    expected_name: SignalName,
    should_have_signal_pressure: bool,
) -> None:
    typed_result = cast(ReplaySignalResult, result)

    assert typed_result.signal_name is expected_name
    assert 0.0 <= float(typed_result.score) <= 1.0
    assert 0.0 <= float(typed_result.confidence) <= 1.0
    assert typed_result.explanation.strip()

    if should_have_signal_pressure:
        assert float(typed_result.score) > 0.0


def test_repeated_calls_fixture_replays() -> None:
    records = _read_jsonl(FIXTURE_DIR / "repeated_calls.jsonl")

    result = _evaluate_repeated_calls(records)

    _assert_replay_result(
        result,
        expected_name=SignalName.REPEATED_CALLS,
        should_have_signal_pressure=True,
    )


def test_error_cascade_fixture_replays() -> None:
    records = _read_jsonl(FIXTURE_DIR / "error_cascade.jsonl")

    result = evaluate_error_cascade(cast(list[object], records))

    _assert_replay_result(
        result,
        expected_name=SignalName.ERROR_CASCADE,
        should_have_signal_pressure=True,
    )


def test_token_burn_fixture_replays() -> None:
    records = _read_jsonl(FIXTURE_DIR / "token_burn.jsonl")

    result = evaluate_token_burn(records)

    _assert_replay_result(
        result,
        expected_name=SignalName.TOKEN_BURN,
        should_have_signal_pressure=True,
    )


def test_context_bloat_fixture_replays() -> None:
    records = _read_jsonl(FIXTURE_DIR / "context_bloat.jsonl")

    result = evaluate_context_saturation(records)

    _assert_replay_result(
        result,
        expected_name=SignalName.CONTEXT_SATURATION,
        should_have_signal_pressure=True,
    )
