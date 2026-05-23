from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_day21_hook_smoke_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/smoke_day21_hooks.py"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert '"status": "passed"' in result.stdout
    assert "day21-smoke-session" in result.stdout
