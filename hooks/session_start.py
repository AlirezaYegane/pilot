#!/usr/bin/env python3
"""Claude Code SessionStart hook entrypoint.

This script intentionally exits 0 even if Pilot fails internally.
Pilot must never break the user's Claude Code session.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap() -> None:
    plugin_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(plugin_root))


def main() -> int:
    try:
        _bootstrap()
        from pilot_core.hook_handlers.session_start import main as handler_main

        return handler_main()
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
