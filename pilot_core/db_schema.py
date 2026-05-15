"""SQLite schema definitions for Pilot.

Day 8 introduced the core session and turn tables.
Day 9 adds event-level tables for tool usage, signal evaluations, and alerts.

This module keeps the Day 8 public API stable while extending the schema for
Day 9.
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TableSchema:
    """Schema metadata for one SQLite table."""

    name: str
    create_sql: str
    expected_columns: tuple[str, ...]


CREATE_SCHEMA_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);
"""

CREATE_SESSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    cwd TEXT,
    model TEXT,
    parent_session_id TEXT,
    total_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
    state TEXT NOT NULL DEFAULT 'healthy' CHECK (state IN ('healthy', 'watching', 'degrading', 'critical', 'handoff_pending', 'handed_off')),
    handoff_summary_path TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
"""

CREATE_TURNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    user_prompt_preview TEXT,
    tool_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    UNIQUE (session_id, turn_index)
);
"""

CREATE_TOOL_USES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tool_uses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_index INTEGER,
    timestamp_ms INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    input_hash TEXT,
    input_size INTEGER NOT NULL DEFAULT 0,
    output_size INTEGER NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 1,
    duration_ms INTEGER,
    input_tokens_est INTEGER NOT NULL DEFAULT 0,
    output_tokens_est INTEGER NOT NULL DEFAULT 0,
    input_preview TEXT,
    output_preview TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
"""

CREATE_SIGNALS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_index INTEGER,
    timestamp_ms INTEGER NOT NULL,
    signal_type TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    health_score REAL NOT NULL,
    state_before TEXT,
    state_after TEXT,
    explanation TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
"""

CREATE_ALERTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_index INTEGER,
    timestamp_ms INTEGER NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    signal_type TEXT,
    health_score REAL,
    state TEXT,
    delivered_to TEXT NOT NULL DEFAULT 'claude',
    created_at INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
"""

SESSIONS_TABLE_SQL = CREATE_SESSIONS_TABLE_SQL
TURNS_TABLE_SQL = CREATE_TURNS_TABLE_SQL
TOOL_USES_TABLE_SQL = CREATE_TOOL_USES_TABLE_SQL
SIGNALS_TABLE_SQL = CREATE_SIGNALS_TABLE_SQL
ALERTS_TABLE_SQL = CREATE_ALERTS_TABLE_SQL


SCHEMA_MIGRATIONS_TABLE = TableSchema(
    name="schema_migrations",
    create_sql=CREATE_SCHEMA_MIGRATIONS_TABLE_SQL,
    expected_columns=("version", "applied_at"),
)

SESSIONS_TABLE = TableSchema(
    name="sessions",
    create_sql=CREATE_SESSIONS_TABLE_SQL,
    expected_columns=(
        "id",
        "started_at",
        "ended_at",
        "cwd",
        "model",
        "parent_session_id",
        "total_input_tokens",
        "total_output_tokens",
        "estimated_cost_usd",
        "state",
        "handoff_summary_path",
        "created_at",
        "updated_at",
    ),
)

TURNS_TABLE = TableSchema(
    name="turns",
    create_sql=CREATE_TURNS_TABLE_SQL,
    expected_columns=(
        "id",
        "session_id",
        "turn_index",
        "started_at",
        "ended_at",
        "user_prompt_preview",
        "tool_count",
        "error_count",
        "created_at",
        "updated_at",
    ),
)

TOOL_USES_TABLE = TableSchema(
    name="tool_uses",
    create_sql=CREATE_TOOL_USES_TABLE_SQL,
    expected_columns=(
        "id",
        "session_id",
        "turn_index",
        "timestamp_ms",
        "tool_name",
        "input_hash",
        "input_size",
        "output_size",
        "success",
        "duration_ms",
        "input_tokens_est",
        "output_tokens_est",
        "input_preview",
        "output_preview",
        "created_at",
    ),
)

SIGNALS_TABLE = TableSchema(
    name="signals",
    create_sql=CREATE_SIGNALS_TABLE_SQL,
    expected_columns=(
        "id",
        "session_id",
        "turn_index",
        "timestamp_ms",
        "signal_type",
        "score",
        "confidence",
        "health_score",
        "state_before",
        "state_after",
        "explanation",
        "created_at",
    ),
)

ALERTS_TABLE = TableSchema(
    name="alerts",
    create_sql=CREATE_ALERTS_TABLE_SQL,
    expected_columns=(
        "id",
        "session_id",
        "turn_index",
        "timestamp_ms",
        "alert_type",
        "severity",
        "message",
        "signal_type",
        "health_score",
        "state",
        "delivered_to",
        "created_at",
    ),
)

TABLES: tuple[TableSchema, ...] = (
    SCHEMA_MIGRATIONS_TABLE,
    SESSIONS_TABLE,
    TURNS_TABLE,
    TOOL_USES_TABLE,
    SIGNALS_TABLE,
    ALERTS_TABLE,
)

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_state ON sessions(state);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);",
    "CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, turn_index);",
    "CREATE INDEX IF NOT EXISTS idx_turns_started_at ON turns(started_at);",
    "CREATE INDEX IF NOT EXISTS idx_tool_uses_session ON tool_uses(session_id, timestamp_ms);",
    "CREATE INDEX IF NOT EXISTS idx_tool_uses_hash ON tool_uses(session_id, input_hash);",
    "CREATE INDEX IF NOT EXISTS idx_tool_uses_turn ON tool_uses(session_id, turn_index);",
    "CREATE INDEX IF NOT EXISTS idx_signals_session ON signals(session_id, timestamp_ms);",
    "CREATE INDEX IF NOT EXISTS idx_signals_type ON signals(session_id, signal_type);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_session ON alerts(session_id, timestamp_ms);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(session_id, severity);",
]

TABLE_SQL = [table.create_sql for table in TABLES]
SCHEMA_SQL = TABLE_SQL + INDEX_SQL


def create_schema_sql() -> str:
    """Return all SQLite schema statements as one executescript-compatible string."""

    return "\n".join(statement.strip() for statement in SCHEMA_SQL if statement.strip())


def schema_statements() -> list[str]:
    """Return all SQLite schema statements in execution order."""

    return [statement.strip() for statement in SCHEMA_SQL if statement.strip()]


def schema_table_names() -> tuple[str, ...]:
    """Return all schema table names, including internal migration metadata."""

    return tuple(table.name for table in TABLES)


def table_names() -> tuple[str, ...]:
    """Return Day 9 product data tables, excluding internal metadata tables."""

    return ("sessions", "turns", "tool_uses", "signals", "alerts")


def expected_columns(table_name: str | TableSchema) -> tuple[str, ...]:
    """Return expected columns for a known table."""

    resolved_name = table_name.name if isinstance(table_name, TableSchema) else table_name

    for table in TABLES:
        if table.name == resolved_name:
            return table.expected_columns

    msg = f"Unknown schema table: {resolved_name}"
    raise ValueError(msg)


def schema_summary() -> dict[str, object]:
    """Return a small serialisable schema summary for CLI/tests."""

    return {
        "schema_version": SCHEMA_VERSION,
        "tables": schema_table_names(),
    }
