"""Verify the Week 1 engineering foundation.

This script intentionally checks project contracts that should stay true before
Week 2 storage work begins.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from pilot_core.config import load_config
from pilot_core.constants import (
    ActivationMode,
    HookEvent,
    SessionState,
    SignalName,
)
from pilot_core.paths import resolve_runtime_paths
from pilot_core.safety import run_safely

REQUIRED_PATHS = (
    ".claude-plugin/plugin.json",
    "hooks/hooks.json",
    "hooks/session_start.py",
    "hooks/user_prompt_submit.py",
    "hooks/pre_tool_use.py",
    "hooks/post_tool_use.py",
    "hooks/post_tool_failure.py",
    "hooks/stop.py",
    "hooks/session_end.py",
    "skills/pilot-status/SKILL.md",
    "skills/pilot-handoff/SKILL.md",
    "skills/pilot-pause/SKILL.md",
    "agents/handoff-generator.md",
    "pilot_core/config.py",
    "pilot_core/constants.py",
    "pilot_core/paths.py",
    "pilot_core/safety.py",
    "docs/project-structure.md",
    "docs/reviews/week1-review.md",
    "docs/milestones/week2-storage.md",
    "docs/issues/week2-storage-issues.md",
)


REQUIRED_MODULES = (
    "pilot_core",
    "pilot_core.config",
    "pilot_core.constants",
    "pilot_core.paths",
    "pilot_core.safety",
)


def _missing_paths(root: Path) -> list[str]:
    return [path for path in REQUIRED_PATHS if not (root / path).exists()]


def _import_failures() -> list[str]:
    failures: list[str] = []

    for module_name in REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            failures.append(f"{module_name}: {type(exc).__name__}: {exc}")

    return failures


def verify_week1(root: Path | None = None) -> list[str]:
    """Return a list of Week 1 contract failures."""

    project_root = root or Path.cwd()
    failures: list[str] = []

    missing = _missing_paths(project_root)
    if missing:
        failures.extend(f"missing path: {path}" for path in missing)

    failures.extend(f"import failed: {failure}" for failure in _import_failures())

    config = load_config()
    if config.signals.default_activation_mode not in ActivationMode.values():
        failures.append("config default activation mode is not a known ActivationMode")

    if len(SignalName.values()) != 8:
        failures.append("expected exactly 8 signal names")

    if len(HookEvent.values()) != 7:
        failures.append("expected exactly 7 hook events")

    if SessionState.HEALTHY.value != "healthy":
        failures.append("SessionState.HEALTHY contract changed")

    paths = resolve_runtime_paths(config)
    if paths.db_path.name != "pilot.db":
        failures.append("runtime db path must end with pilot.db")

    def broken_operation() -> str:
        raise RuntimeError("intentional verification failure")

    fallback = run_safely(broken_operation, default="safe")
    if fallback != "safe":
        failures.append("run_safely did not return fallback on exception")

    return failures


def main() -> int:
    failures = verify_week1()

    if failures:
        print("Week 1 verification failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Week 1 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
