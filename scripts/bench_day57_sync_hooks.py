"""Day 57 sync-hook latency benchmark.

This script benchmarks Claude Code hooks that run synchronously according to
hooks/hooks.json.

Why this exists:
- sync hooks are user-facing latency
- post hooks can be async, but sync hooks must stay lean
- Pilot should detect accidental slowdowns before alpha release

The benchmark runs hook wrapper scripts as subprocesses because that matches
Claude Code's execution model more closely than calling Python functions
directly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = ROOT / "hooks" / "hooks.json"

HEAVY_IMPORT_PATTERNS = (
    "import rich",
    "from rich",
    "import tiktoken",
    "from tiktoken",
    "import requests",
    "from requests",
    "import httpx",
    "from httpx",
    "import pandas",
    "from pandas",
)

IO_PATTERNS = (
    ".read_text(",
    ".write_text(",
    "open(",
    "sqlite3.connect",
)


@dataclass(frozen=True)
class HookCommand:
    """One hook command loaded from hooks/hooks.json."""

    event_name: str
    command: str
    hook_path: Path
    is_async: bool


@dataclass(frozen=True)
class HookLatencyStats:
    """Latency stats for one hook command."""

    iterations: int
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float

    def to_dict(self) -> dict[str, object]:
        """Return a serialisable representation."""

        return {
            "iterations": self.iterations,
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "min_ms": round(self.min_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "mean_ms": round(self.mean_ms, 3),
        }


@dataclass(frozen=True)
class StaticHookAudit:
    """Static source audit for obvious hot-path risks."""

    heavy_import_hits: tuple[str, ...]
    io_hits: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a serialisable representation."""

        return {
            "heavy_import_hits": list(self.heavy_import_hits),
            "io_hits": list(self.io_hits),
            "heavy_import_count": len(self.heavy_import_hits),
            "io_hit_count": len(self.io_hits),
        }


@dataclass(frozen=True)
class HookBenchmark:
    """Benchmark result for one hook."""

    event_name: str
    hook_path: str
    command: str
    latency: HookLatencyStats
    exit_code_failures: int
    timeout_failures: int
    stdout_json_failures: int
    p95_budget_ms: float
    static_audit: StaticHookAudit

    @property
    def passed(self) -> bool:
        """Return True when this hook stayed inside the benchmark contract."""

        return (
            self.latency.p95_ms <= self.p95_budget_ms
            and self.exit_code_failures == 0
            and self.timeout_failures == 0
            and self.stdout_json_failures == 0
        )

    def to_dict(self) -> dict[str, object]:
        """Return a serialisable representation."""

        return {
            "event_name": self.event_name,
            "hook_path": self.hook_path,
            "command": self.command,
            "latency": self.latency.to_dict(),
            "exit_code_failures": self.exit_code_failures,
            "timeout_failures": self.timeout_failures,
            "stdout_json_failures": self.stdout_json_failures,
            "p95_budget_ms": self.p95_budget_ms,
            "passed": self.passed,
            "static_audit": self.static_audit.to_dict(),
        }


def _as_mapping(value: object) -> Mapping[str, object] | None:
    """Return value as a string-keyed mapping when possible."""

    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)

    return None


def _as_sequence(value: object) -> Sequence[object]:
    """Return value as a sequence, excluding text-like values."""

    if isinstance(value, str | bytes | bytearray):
        return ()

    if isinstance(value, Sequence):
        return cast(Sequence[object], value)

    return ()


def _as_bool(value: object, *, default: bool = False) -> bool:
    """Return value as bool when possible."""

    if isinstance(value, bool):
        return value

    return default


def _as_str(value: object, *, default: str = "") -> str:
    """Return value as string when possible."""

    if isinstance(value, str):
        return value

    return default


def hook_path_from_command(command: str) -> Path | None:
    """Extract a hook path from a Claude hook command."""

    match = re.search(r"hooks[/\\]([A-Za-z0-9_]+\.py)", command)
    if match is None:
        return None

    return ROOT / "hooks" / match.group(1)


def load_hook_commands(path: Path = HOOKS_JSON) -> tuple[HookCommand, ...]:
    """Load hook commands from hooks/hooks.json."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    manifest = _as_mapping(raw)
    if manifest is None:
        raise ValueError("hooks/hooks.json must contain an object")

    hooks_raw = _as_mapping(manifest.get("hooks"))
    if hooks_raw is None:
        return ()

    commands: list[HookCommand] = []

    for event_name, event_entries_raw in hooks_raw.items():
        for entry_raw in _as_sequence(event_entries_raw):
            entry = _as_mapping(entry_raw)
            if entry is None:
                continue

            for hook_raw in _as_sequence(entry.get("hooks")):
                hook = _as_mapping(hook_raw)
                if hook is None:
                    continue

                if _as_str(hook.get("type")) != "command":
                    continue

                command = _as_str(hook.get("command"))
                hook_path = hook_path_from_command(command)
                if hook_path is None:
                    continue

                commands.append(
                    HookCommand(
                        event_name=event_name,
                        command=command,
                        hook_path=hook_path,
                        is_async=_as_bool(hook.get("async")),
                    )
                )

    return tuple(commands)


def payload_for_event(event_name: str) -> dict[str, object]:
    """Return a minimal safe benchmark payload for one hook event."""

    base: dict[str, object] = {
        "session_id": f"day57-bench-{event_name.lower()}",
        "cwd": str(ROOT),
        "model": "day57-bench-model",
        "timestamp_ms": 1_750_000_000_000,
        "hook_event_name": event_name,
    }

    if event_name == "UserPromptSubmit":
        base["prompt"] = "benchmark prompt"

    if event_name == "PreToolUse":
        base.update(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
            }
        )

    if event_name == "PostToolUse":
        base.update(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_response": {"content": "benchmark output"},
                "success": True,
            }
        )

    if event_name == "PostToolUseFailure":
        base.update(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "error": "benchmark failure",
                "success": False,
            }
        )

    if event_name == "Stop":
        base.update(
            {
                "state": "healthy",
                "health_score": 0.95,
                "signal_results": [],
                "records": [],
                "activation_mode": "action",
            }
        )

    return base


def make_temp_config(temp_root: Path) -> Path:
    """Create a temporary Pilot config for hook subprocesses."""

    data_dir = temp_root / "pilot-data"
    debug_log_path = temp_root / "debug.log"
    config_path = temp_root / "pilot.yaml"

    config_path.write_text(
        f"""
storage:
  data_dir: "{data_dir.as_posix()}"
  debug_log_path: "{debug_log_path.as_posix()}"
  handoff_dir_name: handoffs
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return config_path


def make_env(config_path: Path) -> dict[str, str]:
    """Return environment variables for hook subprocesses."""

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PILOT_CONFIG"] = str(config_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    env["PYTHONPATH"] = (
        str(ROOT) if existing_pythonpath == "" else str(ROOT) + os.pathsep + existing_pythonpath
    )
    return env


def validate_stdout(stdout: str) -> bool:
    """Return True when hook stdout is empty or valid JSON object text."""

    text = stdout.strip()
    if text == "":
        return True

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False

    return isinstance(parsed, dict)


def run_hook_once(
    hook: HookCommand,
    *,
    env: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[float, int | None, bool, bool]:
    """Run one hook subprocess and return timing/failure metadata."""

    payload = payload_for_event(hook.event_name)
    started = time.perf_counter()

    try:
        completed = subprocess.run(
            [sys.executable, str(hook.hook_path)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=str(ROOT),
            env=dict(env),
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return elapsed_ms, None, True, False

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    stdout_ok = validate_stdout(completed.stdout)

    return elapsed_ms, completed.returncode, False, stdout_ok


def latency_stats(values: Sequence[float]) -> HookLatencyStats:
    """Compute latency stats."""

    if not values:
        raise ValueError("Cannot compute latency stats for empty values")

    sorted_values = sorted(values)
    p95 = (
        statistics.quantiles(sorted_values, n=100, method="inclusive")[94]
        if len(sorted_values) > 1
        else sorted_values[0]
    )

    return HookLatencyStats(
        iterations=len(values),
        p50_ms=statistics.median(sorted_values),
        p95_ms=p95,
        min_ms=min(sorted_values),
        max_ms=max(sorted_values),
        mean_ms=statistics.fmean(sorted_values),
    )


def static_audit_hook(path: Path) -> StaticHookAudit:
    """Inspect hook source for obvious expensive hot-path patterns."""

    if not path.exists():
        return StaticHookAudit(
            heavy_import_hits=("missing hook file",),
            io_hits=("missing hook file",),
        )

    source = path.read_text(encoding="utf-8")

    heavy_hits = tuple(pattern for pattern in HEAVY_IMPORT_PATTERNS if pattern in source)
    io_hits = tuple(pattern for pattern in IO_PATTERNS if pattern in source)

    return StaticHookAudit(
        heavy_import_hits=heavy_hits,
        io_hits=io_hits,
    )


def benchmark_hook(
    hook: HookCommand,
    *,
    env: Mapping[str, str],
    warmups: int,
    iterations: int,
    timeout_seconds: float,
    p95_budget_ms: float,
) -> HookBenchmark:
    """Benchmark one sync hook."""

    if not hook.hook_path.exists():
        raise FileNotFoundError(f"Hook file not found: {hook.hook_path}")

    for _ in range(warmups):
        run_hook_once(hook, env=env, timeout_seconds=timeout_seconds)

    latencies: list[float] = []
    exit_code_failures = 0
    timeout_failures = 0
    stdout_json_failures = 0

    for _ in range(iterations):
        elapsed_ms, return_code, timed_out, stdout_ok = run_hook_once(
            hook,
            env=env,
            timeout_seconds=timeout_seconds,
        )
        latencies.append(elapsed_ms)

        if timed_out:
            timeout_failures += 1
        elif return_code != 0:
            exit_code_failures += 1

        if not stdout_ok:
            stdout_json_failures += 1

    return HookBenchmark(
        event_name=hook.event_name,
        hook_path=str(hook.hook_path.relative_to(ROOT)),
        command=hook.command,
        latency=latency_stats(latencies),
        exit_code_failures=exit_code_failures,
        timeout_failures=timeout_failures,
        stdout_json_failures=stdout_json_failures,
        p95_budget_ms=p95_budget_ms,
        static_audit=static_audit_hook(hook.hook_path),
    )


def build_report(
    *,
    warmups: int,
    iterations: int,
    timeout_seconds: float,
    p95_budget_ms: float,
    event_filter: set[str] | None = None,
) -> dict[str, object]:
    """Run the Day 57 sync hook benchmark and return a report."""

    commands = load_hook_commands()
    sync_hooks = tuple(hook for hook in commands if not hook.is_async)

    if event_filter:
        sync_hooks = tuple(hook for hook in sync_hooks if hook.event_name in event_filter)

    with tempfile.TemporaryDirectory(prefix="pilot-day57-") as temp_name:
        config_path = make_temp_config(Path(temp_name))
        env = make_env(config_path)

        benchmarks = tuple(
            benchmark_hook(
                hook,
                env=env,
                warmups=warmups,
                iterations=iterations,
                timeout_seconds=timeout_seconds,
                p95_budget_ms=p95_budget_ms,
            )
            for hook in sync_hooks
        )

    passed = bool(benchmarks) and all(benchmark.passed for benchmark in benchmarks)

    return {
        "day": 57,
        "purpose": "sync hook latency benchmark",
        "sync_hook_count": len(sync_hooks),
        "iterations": iterations,
        "warmups": warmups,
        "timeout_seconds": timeout_seconds,
        "p95_budget_ms": p95_budget_ms,
        "verdict": "pass" if passed else "fail",
        "hooks": {
            f"{benchmark.event_name}:{Path(benchmark.hook_path).name}": benchmark.to_dict()
            for benchmark in benchmarks
        },
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI args."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--p95-budget-ms", type=float, default=2000.0)
    parser.add_argument(
        "--event",
        action="append",
        default=[],
        help="Only benchmark this hook event. Can be repeated.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run benchmark CLI."""

    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.iterations < 1:
        raise ValueError("--iterations must be >= 1")

    if args.warmups < 0:
        raise ValueError("--warmups must be >= 0")

    event_filter = set(args.event) if args.event else None

    report = build_report(
        warmups=args.warmups,
        iterations=args.iterations,
        timeout_seconds=args.timeout_seconds,
        p95_budget_ms=args.p95_budget_ms,
        event_filter=event_filter,
    )

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
