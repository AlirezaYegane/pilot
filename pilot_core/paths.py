"""Runtime path helpers for Pilot.

This module owns all local runtime paths used by hooks, storage, handoffs,
temporary files, and debug logging.

The goal is simple:
- keep Pilot local-first
- centralise path construction
- make runtime directories predictable
- avoid scattering ~/.claude/plugins/pilot paths across the codebase
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pilot_core.constants import Defaults


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved local runtime paths used by Pilot."""

    data_dir: Path
    handoff_dir: Path
    temp_dir: Path
    debug_log_path: Path
    db_path: Path


def expand_path(value: str | Path) -> Path:
    """Expand user home and environment variables without requiring the path to exist."""

    raw_value = str(value)
    expanded = os.path.expandvars(os.path.expanduser(raw_value))
    return Path(expanded)


def default_data_dir() -> Path:
    """Return Pilot's default local data directory."""

    return Path.home() / ".claude" / "plugins" / "pilot" / Defaults.DEFAULT_DATA_DIR_NAME


def default_debug_log_path() -> Path:
    """Return Pilot's default debug log path."""

    return Path.home() / ".claude" / "plugins" / "pilot" / Defaults.DEFAULT_DEBUG_LOG_NAME


def _get_storage_value(config: Any, name: str, default: str | Path) -> str | Path:
    """Read a storage config value from a flexible config object."""

    storage = getattr(config, "storage", None)
    if storage is None:
        return default
    return getattr(storage, name, default)


def resolve_runtime_paths(config: Any | None = None) -> RuntimePaths:
    """Resolve runtime paths from config, falling back to safe local defaults."""

    if config is None:
        from pilot_core.config import load_config

        config = load_config()

    data_dir = expand_path(_get_storage_value(config, "data_dir", default_data_dir()))
    debug_log_path = expand_path(
        _get_storage_value(config, "debug_log_path", default_debug_log_path())
    )
    handoff_dir_name = str(
        _get_storage_value(config, "handoff_dir_name", Defaults.DEFAULT_HANDOFF_DIR_NAME)
    )

    handoff_dir = data_dir / handoff_dir_name
    temp_dir = data_dir / "tmp"
    db_path = data_dir / "pilot.db"

    return RuntimePaths(
        data_dir=data_dir,
        handoff_dir=handoff_dir,
        temp_dir=temp_dir,
        debug_log_path=debug_log_path,
        db_path=db_path,
    )


def ensure_runtime_dirs(paths: RuntimePaths | None = None) -> RuntimePaths:
    """Create Pilot runtime directories if they do not already exist."""

    resolved = paths or resolve_runtime_paths()

    resolved.data_dir.mkdir(parents=True, exist_ok=True)
    resolved.handoff_dir.mkdir(parents=True, exist_ok=True)
    resolved.temp_dir.mkdir(parents=True, exist_ok=True)
    resolved.debug_log_path.parent.mkdir(parents=True, exist_ok=True)
    resolved.db_path.parent.mkdir(parents=True, exist_ok=True)

    return resolved


def runtime_path_summary(paths: RuntimePaths | None = None) -> dict[str, str]:
    """Return a serialisable summary of the current runtime paths."""

    resolved = paths or resolve_runtime_paths()
    return {
        "data_dir": str(resolved.data_dir),
        "handoff_dir": str(resolved.handoff_dir),
        "temp_dir": str(resolved.temp_dir),
        "debug_log_path": str(resolved.debug_log_path),
        "db_path": str(resolved.db_path),
    }
