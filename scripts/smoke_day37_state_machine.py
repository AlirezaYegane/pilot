"""Day 37 state machine smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Run state-machine transitions over replay fixtures."""

    from pilot_core.constants import SessionState
    from pilot_core.health import compute_health_score
    from pilot_core.state_machine import state_transition_summary, transition_from_health
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

        transition = transition_from_health(SessionState.HEALTHY, health)
        handoff_transition = transition_from_health(
            transition.next_state,
            health,
            handoff_requested=True,
        )

        report[path.stem] = {
            "health_score": round(health.health_score, 4),
            "health_state": health.derived_state.value,
            "transition": state_transition_summary(transition),
            "handoff_request_transition": state_transition_summary(handoff_transition),
        }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
