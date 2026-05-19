#!/usr/bin/env python3
"""PostToolUse hook wrapper.

This script is intentionally tiny:
- read JSON from stdin
- call Pilot's PostToolUse capture logic
- never break the user's Claude Code session
- print nothing on normal success
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _bootstrap_import_path() -> None:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        sys.path.insert(0, plugin_root)
        return

    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))


def main() -> int:
    try:
        _bootstrap_import_path()

        from pilot_core.post_tool_use import handle_post_tool_use
        from pilot_core.safety import log_exception

        try:
            payload = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            log_exception(exc, context="post_tool_use_invalid_json")
            return 0

        handle_post_tool_use(payload)
        return 0

    except Exception as exc:
        try:
            _bootstrap_import_path()
            from pilot_core.safety import log_exception

            log_exception(exc, context="post_tool_use_hook")
        except Exception:
            pass

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
