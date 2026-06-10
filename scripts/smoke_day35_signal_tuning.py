"""Day 35 full 8-signal integration smoke report.

This script evaluates all eight Pilot signals against the Day 34 replay cases
and prints a compact JSON report for false-positive and threshold review.
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


CASE_LIMITS: dict[str, dict[str, float]] = {
    "healthy_session": {"min_fired": 0, "max_fired": 0, "max_score": 0.50},
    "noisy_session": {"min_fired": 0, "max_fired": 1, "max_score": 0.70},
    "ambiguous_session": {"min_fired": 0, "max_fired": 2, "max_score": 0.80},
    "degraded_session": {"min_fired": 5, "max_fired": 8, "max_score": 1.00},
}


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
    values: list[int] = []

    for record in records:
        value = record.get(key)
        if isinstance(value, int):
            values.append(value)

    return max(values) if values else default


def case_float(records: Sequence[RawRecord], key: str, default: float) -> float:
    values: list[float] = []

    for record in records:
        value = record.get(key)
        if isinstance(value, int | float):
            values.append(float(value))

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


def signal_row(result: object) -> dict[str, object]:
    typed = cast(ReplaySignalResult, result)

    return {
        "score": round(float(typed.score), 3),
        "confidence": round(float(typed.confidence), 3),
        "fired": bool(getattr(result, "fired", False)),
        "explanation": typed.explanation,
    }


def case_verdict(case_name: str, fired_count: int, max_score: float) -> str:
    limits = CASE_LIMITS.get(case_name)

    if limits is None:
        return "unknown"

    if fired_count < int(limits["min_fired"]):
        return "under-sensitive"

    if fired_count > int(limits["max_fired"]):
        return "too-sensitive"

    if max_score > limits["max_score"]:
        return "score-too-high"

    return "pass"


def main() -> int:
    summary: dict[str, object] = {}
    exit_code = 0

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        results = evaluate_all(records)
        signal_rows: dict[str, dict[str, object]] = {}

        for result in results:
            typed = cast(ReplaySignalResult, result)
            signal_rows[typed.signal_name.value] = signal_row(result)

        fired_count = sum(1 for row in signal_rows.values() if bool(row["fired"]))

        score_values: list[float] = []
        for row in signal_rows.values():
            score_value = row["score"]
            if not isinstance(score_value, int | float):
                raise TypeError(f"Expected numeric score, got {score_value!r}")
            score_values.append(float(score_value))

        max_score = max(score_values)
        verdict = case_verdict(path.stem, fired_count, max_score)

        if verdict != "pass":
            exit_code = 1

        summary[path.stem] = {
            "record_count": len(records),
            "fired_count": fired_count,
            "max_score": max_score,
            "verdict": verdict,
            "signals": signal_rows,
        }

    print(json.dumps(summary, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
