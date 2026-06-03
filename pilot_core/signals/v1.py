"""Signal Engine v1 runner.

This module provides a small, pure, in-process entrypoint for evaluating the
first v1 degradation signals together.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from pilot_core.constants import SignalName
from pilot_core.signals.context_saturation import evaluate_context_saturation
from pilot_core.signals.error_cascade import evaluate_error_cascade
from pilot_core.signals.token_burn import evaluate_token_burn

RawRecord = Mapping[str, object]


class SignalLikeResult(Protocol):
    """Shared result shape expected from v1 signals."""

    signal_name: SignalName
    score: float
    confidence: float
    explanation: str


SignalEvaluator = Callable[[Sequence[RawRecord]], object]


@dataclass(frozen=True)
class SignalEngineV1Result:
    """Combined result for the first v1 signal bundle."""

    repeated_calls: object
    error_cascade: object
    token_burn: object
    context_saturation: object

    @property
    def results(self) -> tuple[object, object, object, object]:
        """Return results in stable order."""

        return (
            self.repeated_calls,
            self.error_cascade,
            self.token_burn,
            self.context_saturation,
        )

    @property
    def max_score(self) -> float:
        """Return the highest signal score in this bundle."""

        return max(float(cast(SignalLikeResult, result).score) for result in self.results)

    @property
    def fired_count(self) -> int:
        """Return how many signals expose fired=True."""

        return sum(1 for result in self.results if bool(getattr(result, "fired", False)))

    def as_score_map(self) -> dict[str, float]:
        """Return signal scores as a serialisable mapping."""

        score_map: dict[str, float] = {}
        for result in self.results:
            typed = cast(SignalLikeResult, result)
            score_map[typed.signal_name.value] = float(typed.score)
        return score_map


def _evaluate_repeated_calls(records: Sequence[RawRecord]) -> object:
    """Evaluate repeated calls through its public compatibility API."""

    module = importlib.import_module("pilot_core.signals.repeated_calls")
    evaluator = getattr(module, "evaluate_repeated_calls", None)

    if not callable(evaluator):
        raise RuntimeError("pilot_core.signals.repeated_calls must expose evaluate_repeated_calls")

    return cast(SignalEvaluator, evaluator)(records)


def evaluate_signal_engine_v1(records: Sequence[RawRecord]) -> SignalEngineV1Result:
    """Evaluate all first-wave v1 signals against one normalised record stream."""

    error_records: list[object] = list(records)

    return SignalEngineV1Result(
        repeated_calls=_evaluate_repeated_calls(records),
        error_cascade=evaluate_error_cascade(error_records),
        token_burn=evaluate_token_burn(records),
        context_saturation=evaluate_context_saturation(records),
    )


__all__ = [
    "RawRecord",
    "SignalEngineV1Result",
    "SignalLikeResult",
    "evaluate_signal_engine_v1",
]
