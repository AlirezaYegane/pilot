from __future__ import annotations

from scripts.bench_day28_signal_engine import (
    benchmark_signal_engine_v1,
    load_v1_records,
)


def test_signal_engine_v1_benchmark_returns_expected_stats() -> None:
    records = load_v1_records()

    stats = benchmark_signal_engine_v1(records, iterations=10)

    assert stats["iterations"] == 10
    assert stats["record_count"] > 0
    assert stats["p50_ms"] >= 0.0
    assert stats["p95_ms"] >= 0.0
    assert stats["p99_ms"] >= 0.0
    assert isinstance(stats["last_scores"], dict)
    assert isinstance(stats["warmup_scores"], dict)


def test_signal_engine_v1_benchmark_smoke_budget_is_not_absurdly_slow() -> None:
    records = load_v1_records()

    stats = benchmark_signal_engine_v1(records, iterations=20)

    # This is intentionally loose to avoid flaky CI on Windows.
    # The stricter Day 28 budget is enforced by the manual benchmark script.
    assert stats["p95_ms"] < 50.0
