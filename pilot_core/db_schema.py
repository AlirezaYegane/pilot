"""SQLite schema definitions for Pilot storage.

Day 8 scope:
- define schema version metadata
- define sessions table
- define turns table
- define initial indexes
- keep execution separate from storage/bootstrap logic

Bootstrap, migrations, WAL mode, and repository APIs are intentionally left for
later storage days.
"""

from __future__ import annotations

from dataclasses import dataclass

from pilot_core.constants import SessionState

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TableSchema:
    """A SQLite table declaration plus its indexes."""

    name: str
    create_sql: str
    indexes: tuple[str, ...]
    required_columns: tuple[str, ...]


def _quote_sql_string(value: str) -> str:
    """Return a safely quoted SQLite string literal for static schema values."""

    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _sql_in_list(values: tuple[str, ...]) -> str:
    """Return a SQL IN-list from trusted static enum values."""

    return ", ".join(_quote_sql_string(value) for value in values)


SESSION_STATE_SQL_VALUES = _sql_in_list(SessionState.values())


CREATE_SCHEMA_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL,
    description TEXT NOT NULL
);
""".strip()


CREATE_SESSIONS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    cwd TEXT,
    model TEXT,
    parent_session_id TEXT,
    total_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_input_tokens >= 0),
    total_output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_output_tokens >= 0),
    estimated_cost_usd REAL NOT NULL DEFAULT 0.0 CHECK (estimated_cost_usd >= 0.0),
    state TEXT NOT NULL DEFAULT 'healthy' CHECK (state IN ({SESSION_STATE_SQL_VALUES})),
    handoff_summary_path TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id) ON DELETE SET NULL
);
""".strip()


CREATE_TURNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL CHECK (turn_index >= 0),
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    user_prompt_preview TEXT,
    tool_count INTEGER NOT NULL DEFAULT 0 CHECK (tool_count >= 0),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    UNIQUE (session_id, turn_index)
);
""".strip()


SCHEMA_MIGRATIONS_TABLE = TableSchema(
    name="schema_migrations",
    create_sql=CREATE_SCHEMA_MIGRATIONS_TABLE_SQL,
    indexes=(),
    required_columns=("version", "applied_at", "description"),
)


SESSIONS_TABLE = TableSchema(
    name="sessions",
    create_sql=CREATE_SESSIONS_TABLE_SQL,
    indexes=(
        "CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);",
        "CREATE INDEX IF NOT EXISTS idx_sessions_state ON sessions(state);",
        "CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);",
    ),
    required_columns=(
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
    indexes=(
        "CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, turn_index);",
        "CREATE INDEX IF NOT EXISTS idx_turns_started_at ON turns(started_at);",
    ),
    required_columns=(
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


TABLES: tuple[TableSchema, ...] = (
    SCHEMA_MIGRATIONS_TABLE,
    SESSIONS_TABLE,
    TURNS_TABLE,
)


def schema_table_names() -> tuple[str, ...]:
    """Return table names in creation order."""

    return tuple(table.name for table in TABLES)


def expected_columns(table_name: str) -> tuple[str, ...]:
    """Return expected columns for a known schema table."""

    for table in TABLES:
        if table.name == table_name:
            return table.required_columns

    known = ", ".join(schema_table_names())
    msg = f"Unknown schema table: {table_name!r}. Known tables: {known}"
    raise ValueError(msg)


def create_schema_sql() -> str:
    """Return a complete SQL script for the current Day 8 schema."""

    statements: list[str] = []

    for table in TABLES:
        statements.append(table.create_sql)
        statements.extend(table.indexes)

    return "\n\n".join(statements)


def schema_summary() -> dict[str, object]:
    """Return a small serialisable summary for docs, CLI, and tests."""

    return {
        "schema_version": SCHEMA_VERSION,
        "tables": schema_table_names(),
    }
