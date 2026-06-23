#!/usr/bin/env python3
"""Claude Code SessionStart hook for Pilot.

Day 48 wires previous-handoff resume context into SessionStart.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _main() -> int:
    try:
        from pilot_core.session_resume import main

        return main()
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(_main())
