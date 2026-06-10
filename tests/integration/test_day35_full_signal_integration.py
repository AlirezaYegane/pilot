from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class CasePolicy:
    filename: str
    min_fired_count: int
    max_fired_count: int
    min_max_score: float
    max_max_score: float
    required_fired_signals: frozenset[SignalName]
    forbidden_fired_signals: frozenset[SignalName]


CASE_POLICIES: tuple[CasePolicy, ...] = (
    CasePolicy(
        filename="healthy_session.jsonl",
        min_fired_count=0,
        max_fired_count=0,
        min_max_score=0.0,
        max_max_score=0.50,
        required_fired_signals=frozenset(),
        forbidden_fired_signals=frozenset(SignalName),
    ),
    CasePolicy(
        filename="noisy_session.jsonl",
        min_fired_count=0,
        max_fired_count=1,
        min_max_score=0.0,
        max_max_score=0.70,
        required_fired_signals=frozenset(),
        forbidden_fired_signals=frozenset(
            {
                SignalName.TOKEN_BURN,
                SignalName.CONTEXT_SATURATION,
                SignalName.RATE_LIMIT,
            }
        ),
    ),
    CasePolicy(
        filename="ambiguous_session.jsonl",
        min_fired_count=0,
        max_fired_count=2,
        min_max_score=0.0,
        max_max_score=0.80,
        required_fired_signals=frozenset(),
        forbidden_fired_signals=frozenset(
            {
                SignalName.TOKEN_BURN,
                SignalName.CONTEXT_SATURATION,
                SignalName.RATE_LIMIT,
            }
        ),
    ),
    CasePolicy(
        filename="degraded_session.jsonl",
        min_fired_count=5,
        max_fired_count=8,
        min_max_score=0.80,
        max_max_score=1.00,
        required_fired_signals=frozenset(
            {
                SignalName.REPEATED_CALLS,
                SignalName.ERROR_CASCADE,
                SignalName.TOKEN_BURN,
                SignalName.CONTEXT_SATURATION,
                SignalName.SELF_DOUBT,
                SignalName.RATE_LIMIT,
            }
        ),
        forbidden_fired_signals=frozenset(),
    ),
)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        assert isinstance(raw, dict)
        records.append(cast(dict[str, object], raw))

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
    evaluator = getattr(module, "evaluate_repeated_calls", None)

    assert callable(evaluator), "repeated_calls must expose evaluate_repeated_calls"

    return cast(SignalEvaluator, evaluator)(records)


def evaluate_low_productivity_flexible(records: Sequence[RawRecord]) -> object:
    module = importlib.import_module("pilot_core.signals.low_productivity")
    evaluator = getattr(module, "evaluate_low_productivity", None)

    assert callable(evaluator), "low_productivity must expose evaluate_low_productivity"

    baseline = case_float(records, "baseline_productivity_ratio", 0.05)

    attempts: tuple[dict[str, object], ...] = (
        {},
        {"baseline_productivity_ratio": baseline},
        {"baseline_ratio": baseline},
        {"previous_session_productivity_ratio": baseline},
        {"baseline_session_ratio": baseline},
    )

    last_error: TypeError | None = None

    for kwargs in attempts:
        try:
            return cast(SignalEvaluator, evaluator)(records, **kwargs)
        except TypeError as exc:
            last_error = exc

    assert last_error is not None
    raise last_error


def evaluate_all_signals(records: Sequence[RawRecord]) -> dict[SignalName, object]:
    now_ms = case_int(records, "timestamp_ms", 0)
    current_used_tokens = case_int(records, "current_used_tokens", 0)

    results = [
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

    mapped: dict[SignalName, object] = {}

    for result in results:
        typed = cast(ReplaySignalResult, result)
        mapped[typed.signal_name] = result

    return mapped


def score(result: object) -> float:
    return float(cast(ReplaySignalResult, result).score)


def confidence(result: object) -> float:
    return float(cast(ReplaySignalResult, result).confidence)


def explanation(result: object) -> str:
    return str(cast(ReplaySignalResult, result).explanation)


def fired(result: object) -> bool:
    return bool(getattr(result, "fired", False))


def fired_signals(results: Mapping[SignalName, object]) -> frozenset[SignalName]:
    return frozenset(signal_name for signal_name, result in results.items() if fired(result))


def test_day35_all_replay_cases_exist() -> None:
    expected_files = {policy.filename for policy in CASE_POLICIES}
    actual_files = {path.name for path in FIXTURE_DIR.glob("*.jsonl")}

    assert expected_files <= actual_files


def test_day35_every_case_evaluates_all_8_signals() -> None:
    for policy in CASE_POLICIES:
        records = read_jsonl(FIXTURE_DIR / policy.filename)

        results = evaluate_all_signals(records)

        assert set(results) == set(SignalName)
        assert len(results) == 8

        for result in results.values():
            assert 0.0 <= score(result) <= 1.0
            assert 0.0 <= confidence(result) <= 1.0
            assert explanation(result).strip()


def test_day35_case_false_positive_policy() -> None:
    for policy in CASE_POLICIES:
        records = read_jsonl(FIXTURE_DIR / policy.filename)

        results = evaluate_all_signals(records)
        fired_names = fired_signals(results)
        fired_count = len(fired_names)
        max_score = max(score(result) for result in results.values())

        assert policy.min_fired_count <= fired_count <= policy.max_fired_count
        assert policy.min_max_score <= max_score <= policy.max_max_score
        assert policy.required_fired_signals <= fired_names
        assert fired_names.isdisjoint(policy.forbidden_fired_signals)


def test_day35_healthy_session_is_strictly_quiet() -> None:
    records = read_jsonl(FIXTURE_DIR / "healthy_session.jsonl")

    results = evaluate_all_signals(records)

    assert fired_signals(results) == frozenset()
    assert all(score(result) <= 0.50 for result in results.values())


def test_day35_degraded_session_has_clear_multi_signal_pressure() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")

    results = evaluate_all_signals(records)
    fired_names = fired_signals(results)

    assert len(fired_names) >= 5
    assert SignalName.ERROR_CASCADE in fired_names
    assert SignalName.TOKEN_BURN in fired_names
    assert SignalName.RATE_LIMIT in fired_names
    assert max(score(result) for result in results.values()) >= 0.80


def test_day35_noisy_and_ambiguous_do_not_trigger_expensive_resource_signals() -> None:
    for filename in ("noisy_session.jsonl", "ambiguous_session.jsonl"):
        records = read_jsonl(FIXTURE_DIR / filename)
        results = evaluate_all_signals(records)
        fired_names = fired_signals(results)

        assert SignalName.TOKEN_BURN not in fired_names
        assert SignalName.CONTEXT_SATURATION not in fired_names
        assert SignalName.RATE_LIMIT not in fired_names
