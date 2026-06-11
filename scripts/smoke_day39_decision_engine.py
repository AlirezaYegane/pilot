"""Day 39 decision engine smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Run decision-engine smoke scenarios over replay fixtures."""

    from pilot_core.constants import SessionState
    from pilot_core.decision_engine import decide_next_action, decision_summary
    from pilot_core.health import compute_health_score
    from pilot_core.state_machine import transition_from_health_with_hysteresis
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
        normal_decision = decide_next_action(
            transition,
            health=health,
            turn_index=10,
        )
        stop_decision = decide_next_action(
            transition,
            health=health,
            turn_index=10,
            at_stop_hook=True,
        )

        report[path.stem] = {
            "health_score": round(health.health_score, 4),
            "state": transition.next_state.value,
            "normal_decision": decision_summary(normal_decision),
            "stop_hook_decision": decision_summary(stop_decision),
        }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
