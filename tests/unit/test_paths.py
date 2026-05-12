from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pilot_core.paths import (
    RuntimePaths,
    default_data_dir,
    default_debug_log_path,
    ensure_runtime_dirs,
    expand_path,
    resolve_runtime_paths,
    runtime_path_summary,
)


def test_default_paths_are_under_claude_plugin_directory() -> None:
    assert default_data_dir().parts[-4:] == (".claude", "plugins", "pilot", "data")
    assert default_debug_log_path().parts[-4:] == (".claude", "plugins", "pilot", "debug.log")


def test_expand_path_expands_home() -> None:
    expanded = expand_path("~/pilot-test")
    assert isinstance(expanded, Path)
    assert "~" not in str(expanded)


def test_resolve_runtime_paths_from_config(tmp_path: Path) -> None:
    config = SimpleNamespace(
        storage=SimpleNamespace(
            data_dir=str(tmp_path / "pilot-data"),
            debug_log_path=str(tmp_path / "logs" / "debug.log"),
            handoff_dir_name="handoffs",
        )
    )

    paths = resolve_runtime_paths(config)

    assert paths.data_dir == tmp_path / "pilot-data"
    assert paths.handoff_dir == tmp_path / "pilot-data" / "handoffs"
    assert paths.temp_dir == tmp_path / "pilot-data" / "tmp"
    assert paths.debug_log_path == tmp_path / "logs" / "debug.log"
    assert paths.db_path == tmp_path / "pilot-data" / "pilot.db"


def test_ensure_runtime_dirs_creates_required_directories(tmp_path: Path) -> None:
    paths = RuntimePaths(
        data_dir=tmp_path / "data",
        handoff_dir=tmp_path / "data" / "handoffs",
        temp_dir=tmp_path / "data" / "tmp",
        debug_log_path=tmp_path / "logs" / "debug.log",
        db_path=tmp_path / "data" / "pilot.db",
    )

    ensured = ensure_runtime_dirs(paths)

    assert ensured == paths
    assert paths.data_dir.is_dir()
    assert paths.handoff_dir.is_dir()
    assert paths.temp_dir.is_dir()
    assert paths.debug_log_path.parent.is_dir()
    assert paths.db_path.parent.is_dir()


def test_runtime_path_summary_is_serialisable(tmp_path: Path) -> None:
    paths = RuntimePaths(
        data_dir=tmp_path / "data",
        handoff_dir=tmp_path / "data" / "handoffs",
        temp_dir=tmp_path / "data" / "tmp",
        debug_log_path=tmp_path / "debug.log",
        db_path=tmp_path / "data" / "pilot.db",
    )

    summary = runtime_path_summary(paths)

    assert summary == {
        "data_dir": str(tmp_path / "data"),
        "handoff_dir": str(tmp_path / "data" / "handoffs"),
        "temp_dir": str(tmp_path / "data" / "tmp"),
        "debug_log_path": str(tmp_path / "debug.log"),
        "db_path": str(tmp_path / "data" / "pilot.db"),
    }
