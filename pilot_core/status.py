"""Pilot status snapshot helpers.

Day 52 builds the pure status layer used by the CLI.

This module converts signal results or replay records into a single status
snapshot containing:
- health score
- state transition
- ordered signal list
- serialisable summary data

It is intentionally side-effect free except for reading JSONL replay files.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from pilot_core.constants import SessionState, SignalName, parse_signal_name
from pilot_core.health import HealthComputation, compute_health_score
from pilot_core.signals.backtracking import evaluate_backtracking
from pilot_core.signals.context_saturation import evaluate_context_saturation
from pilot_core.signals.error_cascade import evaluate_error_cascade
from pilot_core.signals.rate_limit import evaluate_rate_limit
from pilot_core.signals.self_doubt import evaluate_self_doubt
from pilot_core.signals.token_burn import evaluate_token_burn
from pilot_core.state_machine import StateTransition, transition_from_health_with_hysteresis

RawRecord = Mapping[str, object]
SignalEvaluator = Callable[..., object]


class SignalResultLike(Protocol):
    """Minimal protocol shared by all Pilot signal result objects."""

    signal_name: SignalName
    score: float
    confidence: float
    explanation: str


@dataclass(frozen=True)
class SignalStatus:
    """Normalised signal row for status rendering."""

    signal_name: SignalName
    score: float
    confidence: float
    fired: bool
    explanation: str

    @property
    def display_name(self) -> str:
        """Return a human-readable signal name."""

        return self.signal_name.value.replace("_", " ")


@dataclass(frozen=True)
class PilotStatusSnapshot:
    """Combined status view for one Pilot session."""

    health: HealthComputation
    transition: StateTransition
    signals: tuple[SignalStatus, ...]
    session_id: str | None = None
    source: str = "runtime"

    @property
    def health_score(self) -> float:
        """Return the combined health score."""

        return self.health.health_score

    @property
    def current_state(self) -> SessionState:
        """Return the previous/current session state."""

        return self.transition.previous_state

    @property
    def next_state(self) -> SessionState:
        """Return the next derived session state."""

        return self.transition.next_state

    @property
    def fired_count(self) -> int:
        """Return number of fired signals."""

        return sum(1 for signal in self.signals if signal.fired)

    @property
    def top_signals(self) -> tuple[SignalStatus, ...]:
        """Return signals sorted by score, highest first."""

        return tuple(
            sorted(
                self.signals,
                key=lambda signal: (signal.score, signal.confidence, signal.signal_name.value),
                reverse=True,
            )
        )


def _safe_float(value: object, *, default: float = 0.0) -> float:
    """Convert value to float safely."""

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str | bytes | bytearray):
        try:
            return float(value)
        except ValueError:
            return default

    return default


def _record_get(raw: object, key: str, default: object = None) -> object:
    """Read from mapping-like or object-like values."""

    if isinstance(raw, Mapping):
        return raw.get(key, default)

    return getattr(raw, key, default)


def _normalise_signal_name(value: object) -> SignalName:
    """Normalise a raw signal name."""

    if isinstance(value, SignalName):
        return value

    return parse_signal_name(str(value))


def _fired_from_result(raw: object, *, score: float) -> bool:
    """Read fired flag, falling back to score threshold."""

    value = _record_get(raw, "fired", None)

    if isinstance(value, bool):
        return value

    return score >= 0.60


def normalise_signal_status(
    raw: object,
    *,
    fallback_signal_name: SignalName | None = None,
) -> SignalStatus:
    """Convert a raw signal result into a status row."""

    raw_name = _record_get(raw, "signal_name", fallback_signal_name)
    if raw_name is None:
        raise ValueError("Signal result is missing signal_name")

    signal_name = _normalise_signal_name(raw_name)
    score = max(0.0, min(1.0, _safe_float(_record_get(raw, "score", 0.0))))
    confidence = max(0.0, min(1.0, _safe_float(_record_get(raw, "confidence", 1.0))))
    explanation = str(_record_get(raw, "explanation", "") or "")

    return SignalStatus(
        signal_name=signal_name,
        score=score,
        confidence=confidence,
        fired=_fired_from_result(raw, score=score),
        explanation=explanation,
    )


def normalise_signal_statuses(
    raw_results: Mapping[Any, object] | Sequence[object],
) -> tuple[SignalStatus, ...]:
    """Normalise signal results into deterministic status rows."""

    rows: list[SignalStatus] = []

    if isinstance(raw_results, Mapping):
        for raw_signal_name, raw_result in raw_results.items():
            rows.append(
                normalise_signal_status(
                    raw_result,
                    fallback_signal_name=_normalise_signal_name(raw_signal_name),
                )
            )
    else:
        for raw_result in raw_results:
            rows.append(normalise_signal_status(raw_result))

    return tuple(sorted(rows, key=lambda row: row.signal_name.value))


def build_status_snapshot(
    raw_results: Mapping[Any, object] | Sequence[object],
    *,
    current_state: SessionState = SessionState.HEALTHY,
    session_id: str | None = None,
    source: str = "runtime",
) -> PilotStatusSnapshot:
    """Build a status snapshot from already-evaluated signal results."""

    health = compute_health_score(raw_results)
    transition = transition_from_health_with_hysteresis(current_state, health)
    signals = normalise_signal_statuses(raw_results)

    return PilotStatusSnapshot(
        health=health,
        transition=transition,
        signals=signals,
        session_id=session_id,
        source=source,
    )


def read_jsonl_records(path: str | Path) -> list[dict[str, object]]:
    """Read JSONL replay records."""

    records: list[dict[str, object]] = []
    replay_path = Path(path)

    for line in replay_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"Expected JSON object in {replay_path}: {line!r}")

        records.append(cast(dict[str, object], raw))

    return records


def _case_int(records: Sequence[RawRecord], key: str, default: int) -> int:
    """Return max integer value for a key across records."""

    values: list[int] = []

    for record in records:
        value = record.get(key)
        if isinstance(value, int):
            values.append(value)

    return max(values) if values else default


def _case_float(records: Sequence[RawRecord], key: str, default: float) -> float:
    """Return max float value for a key across records."""

    values: list[float] = []

    for record in records:
        value = record.get(key)
        if isinstance(value, int | float):
            values.append(float(value))

    return max(values) if values else default


def _evaluate_repeated_calls(records: Sequence[RawRecord]) -> object:
    """Evaluate repeated calls through its public compatibility API."""

    module = importlib.import_module("pilot_core.signals.repeated_calls")
    evaluator = getattr(module, "evaluate_repeated_calls", None)

    if not callable(evaluator):
        raise AttributeError("repeated_calls must expose evaluate_repeated_calls")

    return cast(SignalEvaluator, evaluator)(records)


def _evaluate_low_productivity(records: Sequence[RawRecord]) -> object:
    """Evaluate low productivity while supporting older argument names."""

    module = importlib.import_module("pilot_core.signals.low_productivity")
    evaluator = getattr(module, "evaluate_low_productivity", None)

    if not callable(evaluator):
        raise AttributeError("low_productivity must expose evaluate_low_productivity")

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

    if last_error is not None:
        raise last_error

    return cast(SignalEvaluator, evaluator)(records)


def evaluate_signal_results_from_records(
    records: Sequence[RawRecord],
) -> dict[SignalName, object]:
    """Evaluate all eight Pilot signals over replay-like records."""

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
        _evaluate_low_productivity(records),
    ]

    mapped: dict[SignalName, object] = {}

    for result in results:
        typed = cast(SignalResultLike, result)
        mapped[_normalise_signal_name(typed.signal_name)] = result

    return mapped


def build_status_snapshot_from_records(
    records: Sequence[RawRecord],
    *,
    current_state: SessionState = SessionState.HEALTHY,
    session_id: str | None = None,
    source: str = "replay",
) -> PilotStatusSnapshot:
    """Evaluate signals from records and build a status snapshot."""

    signal_results = evaluate_signal_results_from_records(records)
    return build_status_snapshot(
        signal_results,
        current_state=current_state,
        session_id=session_id,
        source=source,
    )


def empty_signal_results() -> dict[SignalName, dict[str, object]]:
    """Return quiet placeholder results for a no-data status view."""

    return {
        signal_name: {
            "signal_name": signal_name,
            "score": 0.0,
            "confidence": 1.0,
            "fired": False,
            "explanation": "No signal data loaded.",
        }
        for signal_name in SignalName
    }


def build_empty_status_snapshot(
    *,
    current_state: SessionState = SessionState.HEALTHY,
    session_id: str | None = None,
) -> PilotStatusSnapshot:
    """Build a quiet status snapshot when no data source is available."""

    return build_status_snapshot(
        empty_signal_results(),
        current_state=current_state,
        session_id=session_id,
        source="empty",
    )


def status_snapshot_summary(snapshot: PilotStatusSnapshot) -> dict[str, object]:
    """Return a JSON-serialisable status summary."""

    return {
        "session_id": snapshot.session_id,
        "source": snapshot.source,
        "health_score": round(snapshot.health_score, 4),
        "current_state": snapshot.current_state.value,
        "next_state": snapshot.next_state.value,
        "transition_reason": snapshot.transition.reason.value,
        "fired_count": snapshot.fired_count,
        "signals": [
            {
                "signal_name": signal.signal_name.value,
                "score": round(signal.score, 4),
                "confidence": round(signal.confidence, 4),
                "fired": signal.fired,
                "explanation": signal.explanation,
            }
            for signal in snapshot.signals
        ],
    }
