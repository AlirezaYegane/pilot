"""Pilot Stop hook wrapper.

The actual implementation lives in pilot_core.stop_handoff.
This wrapper must stay tiny and fail-safe because it runs inside Claude Code.
"""

from __future__ import annotations

from pilot_core.stop_handoff import main

if __name__ == "__main__":
    raise SystemExit(main())
