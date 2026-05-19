#!/usr/bin/env python3
"""Claude Code PreToolUse hook for Pilot.

This hook must be fast and safe:
- read JSON from stdin
- run tiny read-only checks
- optionally print a control JSON object to stdout
- never crash the user's Claude Code session
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _bootstrap_python_path() -> None:
    """Make local pilot_core importable in plugin and repo contexts."""

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        sys.path.insert(0, plugin_root)
        return

    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))


def _load_stdin_json() -> dict[str, Any]:
    """Load hook JSON from stdin and normalise non-object payloads to empty dict."""

    raw = sys.stdin.read()
    if not raw.strip():
        return {}

    payload = json.loads(raw)
    if isinstance(payload, dict):
        return payload

    return {}


def main() -> int:
    """Run the PreToolUse hook."""

    _bootstrap_python_path()

    from pilot_core.pre_tool_policy import evaluate_pre_tool_policy
    from pilot_core.safety import log_exception

    try:
        payload = _load_stdin_json()
        block_on_handoff = os.environ.get("PILOT_PRETOOL_BLOCK", "").lower() in {
            "1",
            "true",
            "yes",
        }

        decision = evaluate_pre_tool_policy(
            payload,
            block_on_handoff=block_on_handoff,
        )
        stdout_payload = decision.to_hook_stdout()

        if stdout_payload:
            print(json.dumps(stdout_payload, ensure_ascii=False))

        return 0
    except Exception as exc:
        log_exception(exc, context="hooks/pre_tool_use.py")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
