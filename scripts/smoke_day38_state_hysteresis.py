"""Day 38 state hysteresis smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Run hysteresis smoke scenarios."""

    from pilot_core.constants import SessionState
    from pilot_core.health import compute_health_score
    from pilot_core.state_machine import (
        apply_hysteresis_sequence,
        state_transition_summary,
        transition_from_health,
        transition_from_health_with_hysteresis,
    )
    from tests.integration.test_day35_full_signal_integration import (
        FIXTURE_DIR,
        evaluate_all_signals,
        read_jsonl,
    )

    replay_report: dict[str, object] = {}

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        signal_results = evaluate_all_signals(records)
        health = compute_health_score(signal_results)

        deterministic = transition_from_health(SessionState.HEALTHY, health)
        hysteresis = transition_from_health_with_hysteresis(SessionState.HEALTHY, health)

        replay_report[path.stem] = {
            "health_score": round(health.health_score, 4),
            "health_state": health.derived_state.value,
            "deterministic": state_transition_summary(deterministic),
            "hysteresis": state_transition_summary(hysteresis),
        }

    boundary_scores = (0.82, 0.79, 0.81, 0.78, 0.80, 0.77)
    boundary_transitions = apply_hysteresis_sequence(
        SessionState.HEALTHY,
        boundary_scores,
    )

    report = {
        "replay_cases": replay_report,
        "boundary_noise_demo": {
            "initial_state": SessionState.HEALTHY.value,
            "scores": list(boundary_scores),
            "states": [transition.next_state.value for transition in boundary_transitions],
            "changed_count": sum(1 for transition in boundary_transitions if transition.changed),
            "verdict": (
                "pass"
                if all(
                    transition.next_state is SessionState.HEALTHY
                    for transition in boundary_transitions
                )
                else "review"
            ),
        },
    }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
