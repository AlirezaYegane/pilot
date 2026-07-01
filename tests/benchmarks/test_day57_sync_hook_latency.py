from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]


def _as_mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, dict)
    return cast(Mapping[str, object], value)


def test_day57_sync_hook_latency_benchmark_smoke() -> None:
    script = ROOT / "scripts" / "bench_day57_sync_hooks.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--iterations",
            "1",
            "--warmups",
            "0",
            "--p95-budget-ms",
            "10000",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout

    report = _as_mapping(json.loads(completed.stdout))
    assert report["day"] == 57
    assert report["verdict"] == "pass"

    sync_hook_count = report["sync_hook_count"]
    assert isinstance(sync_hook_count, int)
    assert sync_hook_count >= 1

    hooks = _as_mapping(report["hooks"])
    assert hooks

    for hook_report_raw in hooks.values():
        hook_report = _as_mapping(hook_report_raw)
        assert hook_report["passed"] is True
        assert hook_report["exit_code_failures"] == 0
        assert hook_report["timeout_failures"] == 0
        assert hook_report["stdout_json_failures"] == 0

        latency = _as_mapping(hook_report["latency"])
        p95_ms = latency["p95_ms"]
        assert isinstance(p95_ms, int | float)
        assert p95_ms >= 0
