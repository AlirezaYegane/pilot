#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook.

This hook records a new turn whenever the user submits a prompt.

It must never block the user:
- read JSON from stdin
- record the turn
- print nothing
- exit 0 even when Pilot fails internally
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _read_payload() -> dict[str, object]:
    """Read and normalise the hook JSON payload from stdin."""

    raw_payload: Any = json.load(sys.stdin)

    if not isinstance(raw_payload, dict):
        msg = "UserPromptSubmit hook payload must be a JSON object"
        raise ValueError(msg)

    return {str(key): value for key, value in raw_payload.items()}


def main() -> int:
    """Run the hook and always return a non-blocking success code."""

    try:
        from pilot_core.turn_events import record_user_prompt_turn

        payload = _read_payload()
        record_user_prompt_turn(payload)
    except Exception as exc:
        try:
            from pilot_core.safety import log_exception

            log_exception(exc, context="hooks.user_prompt_submit")
        except Exception:
            pass
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
