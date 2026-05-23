#!/usr/bin/env python
"""Claude Code PostToolUseFailure hook wrapper."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _plugin_root() -> Path:
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[1]


try:
    root = _plugin_root()
    sys.path.insert(0, str(root))

    from pilot_core.post_tool_failure import main

    raise SystemExit(main())
except SystemExit:
    raise
except Exception as exc:
    try:
        debug_log = Path.home() / ".claude" / "plugins" / "pilot" / "debug.log"
        debug_log.parent.mkdir(parents=True, exist_ok=True)
        with debug_log.open("a", encoding="utf-8") as file:
            file.write(f"post_tool_failure wrapper error: {type(exc).__name__}: {exc}\n")
    except Exception:
        pass

    raise SystemExit(0) from None
