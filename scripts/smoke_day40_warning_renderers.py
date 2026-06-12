"""Day 40 warning renderer smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Run warning renderer smoke scenarios over replay fixtures."""

    from pilot_core.constants import SessionState
    from pilot_core.decision_engine import decide_next_action
    from pilot_core.health import compute_health_score
    from pilot_core.state_machine import transition_from_health_with_hysteresis
    from pilot_core.warnings import (
        render_claude_additional_context,
        render_hook_stdout_payload,
        render_user_stderr,
        warning_summary,
    )
    from tests.integration.test_day35_full_signal_integration import (
        FIXTURE_DIR,
        evaluate_all_signals,
        read_jsonl,
    )

    report: dict[str, object] = {}

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        signal_results = evaluate_all_signals(records)
        health = compute_health_score(signal_results)

        transition = transition_from_health_with_hysteresis(
            SessionState.HEALTHY,
            health,
        )
        decision = decide_next_action(
            transition,
            health=health,
            turn_index=10,
            at_stop_hook=True,
        )

        additional_context = render_claude_additional_context(decision)
        stderr_text = render_user_stderr(decision)
        payload = render_hook_stdout_payload(decision)

        report[path.stem] = {
            "health_score": round(health.health_score, 4),
            "state": transition.next_state.value,
            "summary": warning_summary(decision),
            "payload": payload,
            "additional_context_preview": (
                additional_context[:140] if additional_context is not None else None
            ),
            "stderr_preview": stderr_text[:140] if stderr_text is not None else None,
        }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
