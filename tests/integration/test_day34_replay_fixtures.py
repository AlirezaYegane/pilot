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
class ReplayCaseExpectation:
    filename: str
    min_fired_count: int
    max_fired_count: int
    min_max_score: float
    max_max_score: float


REPLAY_CASE_EXPECTATIONS: tuple[ReplayCaseExpectation, ...] = (
    ReplayCaseExpectation(
        filename="healthy_session.jsonl",
        min_fired_count=0,
        max_fired_count=0,
        min_max_score=0.0,
        max_max_score=0.50,
    ),
    ReplayCaseExpectation(
        filename="noisy_session.jsonl",
        min_fired_count=0,
        max_fired_count=1,
        min_max_score=0.0,
        max_max_score=0.70,
    ),
    ReplayCaseExpectation(
        filename="ambiguous_session.jsonl",
        min_fired_count=0,
        max_fired_count=2,
        min_max_score=0.0,
        max_max_score=0.80,
    ),
    ReplayCaseExpectation(
        filename="degraded_session.jsonl",
        min_fired_count=5,
        max_fired_count=8,
        min_max_score=0.80,
        max_max_score=1.00,
    ),
)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        assert isinstance(raw, dict)
        records.append(cast(dict[str, object], raw))

    return records


def _case_int(records: Sequence[RawRecord], key: str, default: int) -> int:
    values: list[int] = []

    for record in records:
        value = record.get(key)
        if isinstance(value, int):
            values.append(value)

    return max(values) if values else default


def _case_float(records: Sequence[RawRecord], key: str, default: float) -> float:
    values: list[float] = []

    for record in records:
        value = record.get(key)
        if isinstance(value, int | float):
            values.append(float(value))

    return max(values) if values else default


def _evaluate_repeated_calls(records: Sequence[RawRecord]) -> object:
    module = importlib.import_module("pilot_core.signals.repeated_calls")
    evaluator = getattr(module, "evaluate_repeated_calls", None)

    assert callable(evaluator), "repeated_calls must expose evaluate_repeated_calls"

    return cast(SignalEvaluator, evaluator)(records)


def _evaluate_low_productivity_flexible(records: Sequence[RawRecord]) -> object:
    module = importlib.import_module("pilot_core.signals.low_productivity")
    evaluator = getattr(module, "evaluate_low_productivity", None)

    assert callable(evaluator), "low_productivity must expose evaluate_low_productivity"

    baseline = _case_float(records, "baseline_productivity_ratio", 0.05)

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


def _evaluate_all_signals(records: Sequence[RawRecord]) -> dict[SignalName, object]:
    now_ms = _case_int(records, "timestamp_ms", 0)
    current_used_tokens = _case_int(records, "current_used_tokens", 0)

    results = [
        _evaluate_repeated_calls(records),
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
        _evaluate_low_productivity_flexible(records),
    ]

    mapped: dict[SignalName, object] = {}

    for result in results:
        typed = cast(ReplaySignalResult, result)
        mapped[typed.signal_name] = result

    return mapped


def _score(result: object) -> float:
    return float(cast(ReplaySignalResult, result).score)


def _confidence(result: object) -> float:
    return float(cast(ReplaySignalResult, result).confidence)


def _explanation(result: object) -> str:
    return str(cast(ReplaySignalResult, result).explanation)


def _fired(result: object) -> bool:
    return bool(getattr(result, "fired", False))


def _fired_count(results: Mapping[SignalName, object]) -> int:
    return sum(1 for result in results.values() if _fired(result))


def test_day34_replay_fixture_files_exist() -> None:
    expected_files = {expectation.filename for expectation in REPLAY_CASE_EXPECTATIONS}
    actual_files = {path.name for path in FIXTURE_DIR.glob("*.jsonl")}

    assert expected_files <= actual_files


def test_day34_replay_fixtures_are_valid_jsonl() -> None:
    for expectation in REPLAY_CASE_EXPECTATIONS:
        records = _read_jsonl(FIXTURE_DIR / expectation.filename)

        assert len(records) == 13
        assert all("event_id" in record for record in records)
        assert all("case" in record for record in records)


def test_replay_case_signal_pressure_matches_expected_band() -> None:
    for expectation in REPLAY_CASE_EXPECTATIONS:
        records = _read_jsonl(FIXTURE_DIR / expectation.filename)
        results = _evaluate_all_signals(records)

        fired_count = _fired_count(results)
        max_score = max(_score(result) for result in results.values())

        assert expectation.min_fired_count <= fired_count <= expectation.max_fired_count
        assert expectation.min_max_score <= max_score <= expectation.max_max_score


def test_day34_all_cases_evaluate_all_8_signals() -> None:
    for expectation in REPLAY_CASE_EXPECTATIONS:
        records = _read_jsonl(FIXTURE_DIR / expectation.filename)
        results = _evaluate_all_signals(records)

        assert set(results) == set(SignalName)
        assert len(results) == 8

        for result in results.values():
            assert 0.0 <= _score(result) <= 1.0
            assert 0.0 <= _confidence(result) <= 1.0
            assert _explanation(result).strip()


def test_healthy_replay_case_stays_quiet() -> None:
    records = _read_jsonl(FIXTURE_DIR / "healthy_session.jsonl")
    results = _evaluate_all_signals(records)

    assert _fired_count(results) == 0
    assert max(_score(result) for result in results.values()) <= 0.50


def test_degraded_replay_case_has_multi_signal_pressure() -> None:
    records = _read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    results = _evaluate_all_signals(records)

    fired_names = {signal_name for signal_name, result in results.items() if _fired(result)}

    assert len(fired_names) >= 5
    assert SignalName.ERROR_CASCADE in fired_names
    assert SignalName.TOKEN_BURN in fired_names
    assert SignalName.RATE_LIMIT in fired_names
