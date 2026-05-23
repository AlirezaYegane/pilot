#!/usr/bin/env python3
"""Claude Code Stop hook wrapper for Pilot."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast


def _bootstrap_path() -> None:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        sys.path.insert(0, plugin_root)
        return

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    _bootstrap_path()

    try:
        from pilot_core.hook_lifecycle import process_stop_payload
        from pilot_core.safety import log_exception

        raw_payload: Any = json.load(sys.stdin)
        payload = cast(dict[str, Any], raw_payload if isinstance(raw_payload, dict) else {})

        result = process_stop_payload(payload)
        stdout_payload = result.stdout_payload()

        if stdout_payload:
            print(json.dumps(stdout_payload, ensure_ascii=False))

        return 0
    except Exception as exc:
        try:
            from pilot_core.safety import log_exception

            log_exception(exc, context="hooks.stop")
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
