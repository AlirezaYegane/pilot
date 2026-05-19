from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_pre_tool_use_hook_allows_minimal_payload() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    hook_path = repo_root / "hooks" / "pre_tool_use.py"

    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(repo_root)

    payload = {
        "session_id": "smoke-session",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
    }

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
