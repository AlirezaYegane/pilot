from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pilot_core.storage_benchmarks import (
    BenchmarkConfig,
    connect_sqlite,
    create_benchmark_schema,
    run_local_hot_path_benchmark,
    verify_schema_v1,
)


def test_benchmark_schema_satisfies_schema_v1_contract(tmp_path: Path) -> None:
    db_path = tmp_path / "pilot.db"
    conn = connect_sqlite(db_path)
    create_benchmark_schema(conn)

    result = verify_schema_v1(conn)

    conn.close()

    assert result["ok"] is True
    assert result["missing_tables"] == []
    assert result["missing_index_prefixes"] == []


def test_local_hot_path_benchmark_returns_serialisable_result(tmp_path: Path) -> None:
    result: dict[str, Any] = run_local_hot_path_benchmark(
        tmp_path / "pilot.db",
        BenchmarkConfig(
            iterations=10,
            concurrency_writers=2,
            concurrency_events_per_writer=5,
            busy_timeout_ms=5_000,
        ),
    )

    json.dumps(result)

    assert result["schema_v1"]["ok"] is True
    assert result["locking_probe"]["ok"] is True
    assert result["locking_probe"]["errors"] == []


def test_hot_path_timings_include_expected_operations(tmp_path: Path) -> None:
    result = run_local_hot_path_benchmark(
        tmp_path / "pilot.db",
        BenchmarkConfig(
            iterations=5,
            concurrency_writers=2,
            concurrency_events_per_writer=3,
            busy_timeout_ms=5_000,
        ),
    )

    timings = result["timings"]

    assert set(timings) == {
        "insert_turn",
        "insert_tool_use",
        "select_recent_tool_uses",
        "update_session_state",
    }

    for summary in timings.values():
        assert summary["count"] == 5
        assert summary["p50_ms"] >= 0.0
        assert summary["p95_ms"] >= 0.0
        assert summary["max_ms"] >= 0.0
