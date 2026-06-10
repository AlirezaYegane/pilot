"""Smoke test Day 34 replay fixtures.

Prints a compact JSON summary for the four scenario-level replay fixtures.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from pilot_core.constants import SignalName
from pilot_core.signals.backtracking import evaluate_backtracking
from pilot_core.signals.context_saturation import evaluate_context_saturation
from pilot_core.signals.error_cascade import evaluate_error_cascade
from pilot_core.signals.rate_limit import evaluate_rate_limit
from pilot_core.signals.self_doubt import evaluate_self_doubt
from pilot_core.signals.token_burn import evaluate_token_burn

RawRecord = Mapping[str, object]
SignalEvaluator = Callable[..., object]
FIXTURE_DIR = Path("tests") / "fixtures" / "replay_cases"


class ReplaySignalResult(Protocol):
    signal_name: SignalName
    score: float
    confidence: float
    explanation: str


def read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"Expected JSON object in {path}: {line!r}")
        records.append(raw)

    return records


def case_int(records: Sequence[RawRecord], key: str, default: int) -> int:
    values = [value for record in records if isinstance((value := record.get(key)), int)]
    return max(values) if values else default


def case_float(records: Sequence[RawRecord], key: str, default: float) -> float:
    values = [
        float(value) for record in records if isinstance((value := record.get(key)), int | float)
    ]
    return max(values) if values else default


def evaluate_repeated_calls(records: Sequence[RawRecord]) -> object:
    module = importlib.import_module("pilot_core.signals.repeated_calls")
    evaluator = module.evaluate_repeated_calls
    return cast(SignalEvaluator, evaluator)(records)


def evaluate_low_productivity_flexible(records: Sequence[RawRecord]) -> object:
    module = importlib.import_module("pilot_core.signals.low_productivity")
    evaluator = module.evaluate_low_productivity
    baseline = case_float(records, "baseline_productivity_ratio", 0.05)

    for kwargs in (
        {},
        {"baseline_productivity_ratio": baseline},
        {"baseline_ratio": baseline},
        {"previous_session_productivity_ratio": baseline},
        {"baseline_session_ratio": baseline},
    ):
        try:
            return cast(SignalEvaluator, evaluator)(records, **kwargs)
        except TypeError:
            continue

    return cast(SignalEvaluator, evaluator)(records)


def evaluate_all(records: Sequence[RawRecord]) -> list[object]:
    now_ms = case_int(records, "timestamp_ms", 0)
    current_used_tokens = case_int(records, "current_used_tokens", 0)

    return [
        evaluate_repeated_calls(records),
        evaluate_error_cascade(cast(list[object], list(records))),
        evaluate_token_burn(records),
        evaluate_context_saturation(records),
        evaluate_backtracking(records),
        evaluate_self_doubt(records),
        evaluate_rate_limit(
            records,
            current_used_tokens=current_used_tokens,
            now_ms=now_ms,
        ),
        evaluate_low_productivity_flexible(records),
    ]


def main() -> int:
    summary: dict[str, object] = {}

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        results = evaluate_all(records)
        signal_rows: dict[str, object] = {}

        for result in results:
            typed = cast(ReplaySignalResult, result)
            signal_rows[typed.signal_name.value] = {
                "score": round(float(typed.score), 3),
                "confidence": round(float(typed.confidence), 3),
                "fired": bool(getattr(result, "fired", False)),
            }

        summary[path.stem] = {
            "record_count": len(records),
            "fired_count": sum(
                1 for row in signal_rows.values() if bool(cast(dict[str, object], row)["fired"])
            ),
            "signals": signal_rows,
        }

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
