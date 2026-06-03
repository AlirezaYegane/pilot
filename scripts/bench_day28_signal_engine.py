"""Benchmark Signal Engine v1 hot path.

This is an in-process benchmark, not a subprocess hook benchmark.

Why:
- Day 28 focuses on signal evaluation cost, not Python process startup cost.
- Hook subprocess latency will be benchmarked separately when hook packaging is final.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from pathlib import Path
from statistics import mean
from typing import TypedDict

from pilot_core.signals.v1 import RawRecord, evaluate_signal_engine_v1

DEFAULT_ITERATIONS = 1_000
DEFAULT_P95_BUDGET_MS = 10.0
FIXTURE_DIR = Path("tests") / "fixtures"


class SignalEngineBenchmarkStats(TypedDict):
    """Serialisable benchmark statistics."""

    iterations: int
    record_count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    max_ms: float
    warmup_scores: dict[str, float]
    last_scores: dict[str, float]
    last_fired_count: int


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"Expected JSON object in {path}: {line!r}")

        records.append(raw)

    return records


def load_v1_records() -> list[dict[str, object]]:
    """Load and combine current v1 replay fixtures."""

    records: list[dict[str, object]] = []

    for filename in (
        "repeated_calls.jsonl",
        "error_cascade.jsonl",
        "token_burn.jsonl",
        "context_bloat.jsonl",
    ):
        path = FIXTURE_DIR / filename
        if path.exists():
            records.extend(_read_jsonl(path))

    if not records:
        raise RuntimeError("No Signal Engine v1 fixture records found.")

    return records


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Return nearest-rank percentile from sorted values."""

    if not sorted_values:
        raise ValueError("sorted_values must not be empty")

    index = round((len(sorted_values) - 1) * pct)
    return sorted_values[index]


def benchmark_signal_engine_v1(
    records: Sequence[RawRecord],
    *,
    iterations: int = DEFAULT_ITERATIONS,
) -> SignalEngineBenchmarkStats:
    """Benchmark v1 signal evaluation and return serialisable stats."""

    if iterations <= 0:
        raise ValueError("iterations must be greater than 0")

    warmup_result = evaluate_signal_engine_v1(records)

    timings_ms: list[float] = []
    result = warmup_result

    for _ in range(iterations):
        started_ns = time.perf_counter_ns()
        result = evaluate_signal_engine_v1(records)
        elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        timings_ms.append(elapsed_ms)

    timings_ms.sort()

    return {
        "iterations": iterations,
        "record_count": len(records),
        "p50_ms": percentile(timings_ms, 0.50),
        "p95_ms": percentile(timings_ms, 0.95),
        "p99_ms": percentile(timings_ms, 0.99),
        "mean_ms": mean(timings_ms),
        "max_ms": timings_ms[-1],
        "warmup_scores": warmup_result.as_score_map(),
        "last_scores": result.as_score_map(),
        "last_fired_count": result.fired_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Signal Engine v1 hot path.")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--p95-budget-ms", type=float, default=DEFAULT_P95_BUDGET_MS)
    parser.add_argument("--json", action="store_true", help="Print compact JSON only.")
    args = parser.parse_args()

    records = load_v1_records()
    stats = benchmark_signal_engine_v1(records, iterations=args.iterations)

    if args.json:
        print(json.dumps(stats, sort_keys=True))
    else:
        print(json.dumps(stats, indent=2, sort_keys=True))

    p95_ms = stats["p95_ms"]
    if p95_ms > args.p95_budget_ms:
        print(f"Signal Engine v1 p95 budget exceeded: {p95_ms:.3f}ms > {args.p95_budget_ms:.3f}ms")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
