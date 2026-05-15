"""Storage entrypoints for Pilot.

Day 10 keeps this module intentionally thin. Repository-level CRUD methods are
implemented in Day 11 and Day 12.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from pilot_core.db_migrations import (
    DatabaseBootstrapResult,
    bootstrap_database,
    database_health,
    open_bootstrapped_connection,
)


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Return an open, bootstrapped SQLite connection."""

    return open_bootstrapped_connection(db_path=db_path)


def ensure_database(db_path: str | Path | None = None) -> DatabaseBootstrapResult:
    """Ensure the Pilot database exists and migrations have been applied."""

    return bootstrap_database(db_path=db_path)


def healthcheck(db_path: str | Path | None = None) -> dict[str, Any]:
    """Return storage health diagnostics."""

    return database_health(db_path=db_path)


__all__ = [
    "DatabaseBootstrapResult",
    "bootstrap_database",
    "database_health",
    "ensure_database",
    "get_connection",
    "healthcheck",
    "open_bootstrapped_connection",
]
