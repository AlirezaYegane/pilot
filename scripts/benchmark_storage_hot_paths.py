from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from pilot_core.storage_benchmarks import (
    BenchmarkConfig,
    dump_benchmark_json,
    run_local_hot_path_benchmark,
)


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _render_markdown(result: dict[str, Any]) -> str:
    timings = result["timings"]
    locking = result["locking_probe"]
    schema = result["schema_v1"]

    lines = [
        "# Day 14 Storage Hot-Path Benchmark",
        "",
        "## Summary",
        "",
        f"- Schema v1 check: **{_status(bool(schema['ok']))}**",
        f"- Locking probe: **{_status(bool(locking['ok']))}**",
        f"- DB path: `{result['db_path']}`",
        "",
        "## Hot-path timings",
        "",
        "| Operation | Count | p50 ms | p95 ms | Max ms |",
        "|---|---:|---:|---:|---:|",
    ]

    for operation, summary in timings.items():
        lines.append(
            "| "
            f"{operation} | "
            f"{summary['count']} | "
            f"{summary['p50_ms']} | "
            f"{summary['p95_ms']} | "
            f"{summary['max_ms']} |"
        )

    lines.extend(
        [
            "",
            "## Locking probe",
            "",
            "| Writers | Events / writer | Expected events | Actual events | Errors |",
            "|---:|---:|---:|---:|---:|",
            "| "
            f"{locking['writers']} | "
            f"{locking['events_per_writer']} | "
            f"{locking['expected_events']} | "
            f"{locking['actual_events']} | "
            f"{len(locking['errors'])} |",
            "",
            "## Schema v1 tables",
            "",
        ]
    )

    for table in schema["tables"]:
        lines.append(f"- `{table}`")

    lines.extend(
        [
            "",
            "## Schema v1 indexes",
            "",
        ]
    )

    for index in schema["indexes"]:
        lines.append(f"- `{index}`")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Day 14 does not claim production performance yet. It creates a repeatable baseline",
            "for local SQLite hot paths before hook plumbing begins in Week 3.",
            "",
            "The important checks are:",
            "",
            "- schema v1 surface exists",
            "- WAL/busy-timeout concurrent writes complete without lock errors",
            "- insert/select/update operations have a measured baseline",
            "- results are saved as reproducible evidence",
            "",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Day 14 SQLite storage hot-path benchmark.")
    parser.add_argument(
        "--db-path",
        default="artifacts/day14/day14_storage_benchmark.db",
        help="SQLite database path used for the benchmark.",
    )
    parser.add_argument(
        "--json-out",
        default="artifacts/day14/storage_hot_paths.json",
        help="Where to write the JSON benchmark result.",
    )
    parser.add_argument(
        "--markdown-out",
        default="docs/benchmarks/day14-storage-hot-paths.md",
        help="Where to write the markdown benchmark report.",
    )
    parser.add_argument("--iterations", type=int, default=250)
    parser.add_argument("--writers", type=int, default=4)
    parser.add_argument("--events-per-writer", type=int, default=50)
    parser.add_argument("--busy-timeout-ms", type=int, default=5_000)

    args = parser.parse_args()

    config = BenchmarkConfig(
        iterations=args.iterations,
        concurrency_writers=args.writers,
        concurrency_events_per_writer=args.events_per_writer,
        busy_timeout_ms=args.busy_timeout_ms,
    )

    result = run_local_hot_path_benchmark(Path(args.db_path), config)

    json_out = Path(args.json_out)
    markdown_out = Path(args.markdown_out)

    dump_benchmark_json(result, json_out)

    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.write_text(_render_markdown(result), encoding="utf-8")

    schema_ok = bool(result["schema_v1"]["ok"])
    locking_ok = bool(result["locking_probe"]["ok"])

    print(f"Schema v1: {_status(schema_ok)}")
    print(f"Locking probe: {_status(locking_ok)}")
    print(f"JSON report: {json_out}")
    print(f"Markdown report: {markdown_out}")

    if not schema_ok or not locking_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
