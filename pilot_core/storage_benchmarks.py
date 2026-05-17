"""SQLite storage benchmark and schema inspection helpers.

Day 14 freezes the Week 2 storage layer by checking:
- local SQLite hot-path timings
- WAL and busy-timeout behaviour
- basic concurrent writer safety
- schema v1 table/index presence

These helpers are intentionally independent from hook code. They are safe to
run in tests, CI, and local evidence-generation scripts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REQUIRED_SCHEMA_V1_TABLES: tuple[str, ...] = (
    "schema_migrations",
    "sessions",
    "turns",
    "tool_uses",
    "signals",
    "alerts",
)

REQUIRED_SCHEMA_V1_INDEX_PREFIXES: tuple[str, ...] = (
    "idx_sessions_",
    "idx_turns_",
    "idx_tool_uses_",
    "idx_signals_",
    "idx_alerts_",
)


@dataclass(frozen=True)
class BenchmarkConfig:
    """Configuration for local storage benchmarks."""

    iterations: int = 250
    concurrency_writers: int = 4
    concurrency_events_per_writer: int = 50
    busy_timeout_ms: int = 5_000


@dataclass(frozen=True)
class TimingSummary:
    """Small percentile summary for one hot path."""

    count: int
    min_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


def connect_sqlite(db_path: Path, *, busy_timeout_ms: int = 5_000) -> sqlite3.Connection:
    """Open a SQLite connection with Pilot's runtime safety pragmas."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        timeout=busy_timeout_ms / 1_000,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms};")
    return conn


def create_benchmark_schema(conn: sqlite3.Connection) -> None:
    """Create a minimal schema-v1-compatible database for local benchmarks.

    The real project schema remains the source of truth. This function gives
    the benchmark script and tests a deterministic SQLite target.
    """

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            cwd TEXT,
            model TEXT,
            parent_session_id TEXT,
            total_input_tokens INTEGER DEFAULT 0,
            total_output_tokens INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0,
            state TEXT DEFAULT 'healthy',
            handoff_summary_path TEXT
        );

        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_index INTEGER NOT NULL,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            user_prompt_preview TEXT,
            tool_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS tool_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_index INTEGER,
            timestamp_ms INTEGER,
            tool_name TEXT,
            input_hash TEXT,
            input_size INTEGER,
            output_size INTEGER,
            success INTEGER,
            duration_ms INTEGER,
            input_tokens_est INTEGER,
            output_tokens_est INTEGER,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp_ms INTEGER,
            signal_type TEXT,
            score REAL,
            health_score REAL,
            state_before TEXT,
            state_after TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp_ms INTEGER,
            alert_type TEXT,
            severity TEXT,
            message TEXT,
            acknowledged INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_started_at
            ON sessions(started_at);
        CREATE INDEX IF NOT EXISTS idx_sessions_state
            ON sessions(state);
        CREATE INDEX IF NOT EXISTS idx_sessions_parent
            ON sessions(parent_session_id);

        CREATE INDEX IF NOT EXISTS idx_turns_session
            ON turns(session_id, turn_index);

        CREATE INDEX IF NOT EXISTS idx_tool_uses_session
            ON tool_uses(session_id, timestamp_ms);
        CREATE INDEX IF NOT EXISTS idx_tool_uses_hash
            ON tool_uses(session_id, input_hash);

        CREATE INDEX IF NOT EXISTS idx_signals_session
            ON signals(session_id, timestamp_ms);
        CREATE INDEX IF NOT EXISTS idx_signals_type
            ON signals(signal_type);

        CREATE INDEX IF NOT EXISTS idx_alerts_session
            ON alerts(session_id, timestamp_ms);
        CREATE INDEX IF NOT EXISTS idx_alerts_severity
            ON alerts(severity);
        """
    )


def sqlite_schema_summary(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Return tables and indexes currently present in the database."""

    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ).fetchall()
        if not str(row[0]).startswith("sqlite_")
    ]
    indexes = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name;"
        ).fetchall()
        if row[0] is not None and not str(row[0]).startswith("sqlite_")
    ]
    return {"tables": tables, "indexes": indexes}


def verify_schema_v1(conn: sqlite3.Connection) -> dict[str, Any]:
    """Verify the required Week 2 schema-v1 surface."""

    summary = sqlite_schema_summary(conn)
    tables = set(summary["tables"])
    indexes = set(summary["indexes"])

    missing_tables = [table for table in REQUIRED_SCHEMA_V1_TABLES if table not in tables]
    missing_index_prefixes = [
        prefix
        for prefix in REQUIRED_SCHEMA_V1_INDEX_PREFIXES
        if not any(index.startswith(prefix) for index in indexes)
    ]

    return {
        "ok": not missing_tables and not missing_index_prefixes,
        "missing_tables": missing_tables,
        "missing_index_prefixes": missing_index_prefixes,
        "tables": summary["tables"],
        "indexes": summary["indexes"],
    }


def percentile(samples: Sequence[float], ratio: float) -> float:
    """Return a simple nearest-rank percentile."""

    if not samples:
        return 0.0

    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def summarise_timings(samples: Sequence[float]) -> TimingSummary:
    """Summarise timing samples in milliseconds."""

    if not samples:
        return TimingSummary(count=0, min_ms=0.0, p50_ms=0.0, p95_ms=0.0, max_ms=0.0)

    return TimingSummary(
        count=len(samples),
        min_ms=round(min(samples), 4),
        p50_ms=round(percentile(samples, 0.50), 4),
        p95_ms=round(percentile(samples, 0.95), 4),
        max_ms=round(max(samples), 4),
    )


def measure_ms(operation: Callable[[], object]) -> float:
    """Measure one operation in milliseconds."""

    start = time.perf_counter()
    _ = operation()
    return (time.perf_counter() - start) * 1_000


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def run_locking_probe(db_path: Path, config: BenchmarkConfig) -> dict[str, Any]:
    """Run a small multi-writer probe against SQLite WAL mode."""

    errors: list[str] = []
    errors_lock = threading.Lock()

    def writer(worker_id: int) -> None:
        try:
            conn = connect_sqlite(db_path, busy_timeout_ms=config.busy_timeout_ms)
            session_id = f"concurrent-{worker_id}"
            conn.execute(
                """
                INSERT OR IGNORE INTO sessions (id, started_at, cwd, model, state)
                VALUES (?, ?, ?, ?, ?);
                """,
                (session_id, _now_ms(), "bench", "claude", "healthy"),
            )

            for event_index in range(config.concurrency_events_per_writer):
                conn.execute(
                    """
                    INSERT INTO tool_uses (
                        session_id,
                        turn_index,
                        timestamp_ms,
                        tool_name,
                        input_hash,
                        input_size,
                        output_size,
                        success,
                        duration_ms,
                        input_tokens_est,
                        output_tokens_est
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        session_id,
                        event_index,
                        _now_ms(),
                        "Bash",
                        f"hash-{worker_id}-{event_index}",
                        120,
                        240,
                        1,
                        8,
                        30,
                        60,
                    ),
                )
            conn.close()
        except Exception as exc:
            with errors_lock:
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [
        threading.Thread(target=writer, args=(worker_id,))
        for worker_id in range(config.concurrency_writers)
    ]

    start = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed_ms = (time.perf_counter() - start) * 1_000

    expected_events = config.concurrency_writers * config.concurrency_events_per_writer

    conn = connect_sqlite(db_path, busy_timeout_ms=config.busy_timeout_ms)
    actual_events = int(
        conn.execute(
            "SELECT COUNT(*) FROM tool_uses WHERE session_id LIKE 'concurrent-%';"
        ).fetchone()[0]
    )
    conn.close()

    return {
        "writers": config.concurrency_writers,
        "events_per_writer": config.concurrency_events_per_writer,
        "expected_events": expected_events,
        "actual_events": actual_events,
        "errors": errors,
        "elapsed_ms": round(elapsed_ms, 4),
        "ok": not errors and actual_events == expected_events,
    }


def run_local_hot_path_benchmark(
    db_path: Path,
    config: BenchmarkConfig | None = None,
) -> dict[str, Any]:
    """Run local SQLite hot-path benchmarks and return JSON-serialisable results."""

    cfg = config or BenchmarkConfig()
    conn = connect_sqlite(db_path, busy_timeout_ms=cfg.busy_timeout_ms)
    create_benchmark_schema(conn)

    conn.execute(
        """
        INSERT OR IGNORE INTO sessions (id, started_at, cwd, model, state)
        VALUES (?, ?, ?, ?, ?);
        """,
        ("bench-session", _now_ms(), "bench", "claude", "healthy"),
    )

    timings: dict[str, list[float]] = {
        "insert_turn": [],
        "insert_tool_use": [],
        "select_recent_tool_uses": [],
        "update_session_state": [],
    }

    for index in range(cfg.iterations):

        def insert_turn_operation(current_index: int = index) -> object:
            return conn.execute(
                """
                INSERT INTO turns (
                    session_id,
                    turn_index,
                    started_at,
                    user_prompt_preview,
                    tool_count,
                    error_count
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                ("bench-session", current_index, _now_ms(), "benchmark prompt", 0, 0),
            )

        timings["insert_turn"].append(measure_ms(insert_turn_operation))

        def insert_tool_use_operation(current_index: int = index) -> object:
            return conn.execute(
                """
                INSERT INTO tool_uses (
                    session_id,
                    turn_index,
                    timestamp_ms,
                    tool_name,
                    input_hash,
                    input_size,
                    output_size,
                    success,
                    duration_ms,
                    input_tokens_est,
                    output_tokens_est
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "bench-session",
                    current_index,
                    _now_ms(),
                    "Read",
                    f"bench-hash-{current_index}",
                    128,
                    256,
                    1,
                    12,
                    32,
                    64,
                ),
            )

        timings["insert_tool_use"].append(measure_ms(insert_tool_use_operation))

        def select_recent_tool_uses_operation() -> object:
            return conn.execute(
                """
                SELECT tool_name, input_hash, timestamp_ms
                FROM tool_uses
                WHERE session_id = ?
                ORDER BY timestamp_ms DESC
                LIMIT 10;
                """,
                ("bench-session",),
            ).fetchall()

        timings["select_recent_tool_uses"].append(measure_ms(select_recent_tool_uses_operation))

        next_state = "watching" if index % 2 == 0 else "healthy"

        def update_session_state_operation(state: str = next_state) -> object:
            return conn.execute(
                "UPDATE sessions SET state = ? WHERE id = ?;",
                (state, "bench-session"),
            )

        timings["update_session_state"].append(measure_ms(update_session_state_operation))

    schema = verify_schema_v1(conn)
    conn.close()

    locking_probe = run_locking_probe(db_path, cfg)

    return {
        "db_path": str(db_path),
        "config": asdict(cfg),
        "schema_v1": schema,
        "timings": {name: asdict(summarise_timings(samples)) for name, samples in timings.items()},
        "locking_probe": locking_probe,
    }


def dump_benchmark_json(result: dict[str, Any], out_path: Path) -> None:
    """Write benchmark result as pretty JSON."""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
