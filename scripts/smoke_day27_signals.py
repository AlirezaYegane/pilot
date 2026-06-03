from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from pilot_core.constants import Severity, SignalName
from pilot_core.signals.context_saturation import evaluate_context_saturation
from pilot_core.signals.error_cascade import evaluate_error_cascade
from pilot_core.signals.token_burn import evaluate_token_burn

RawRecord = Mapping[str, object]
SignalEvaluator = Callable[[Sequence[RawRecord]], object]


class SmokeSignalResult(Protocol):
    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    explanation: str


def read_jsonl(path: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise TypeError(f"Expected JSON object line in {path}")

        records.append(cast(dict[str, object], raw))

    return records


def evaluate_repeated_calls(records: Sequence[RawRecord]) -> object:
    module = importlib.import_module("pilot_core.signals.repeated_calls")
    evaluator = module.evaluate_repeated_calls
    return cast(SignalEvaluator, evaluator)(records)


def compact_result(result: object) -> dict[str, object]:
    typed_result = cast(SmokeSignalResult, result)

    return {
        "signal_name": str(typed_result.signal_name),
        "score": typed_result.score,
        "confidence": typed_result.confidence,
        "severity": str(typed_result.severity),
        "fired": getattr(result, "fired", None),
        "explanation": typed_result.explanation,
    }


def main() -> None:
    results = {
        "repeated_calls": compact_result(
            evaluate_repeated_calls(read_jsonl("tests/fixtures/repeated_calls.jsonl"))
        ),
        "error_cascade": compact_result(
            evaluate_error_cascade(
                cast(list[object], read_jsonl("tests/fixtures/error_cascade.jsonl"))
            )
        ),
        "token_burn": compact_result(
            evaluate_token_burn(read_jsonl("tests/fixtures/token_burn.jsonl"))
        ),
        "context_saturation": compact_result(
            evaluate_context_saturation(read_jsonl("tests/fixtures/context_bloat.jsonl"))
        ),
    }

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
