"""Day 42 policy runtime smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Run policy runtime over replay fixtures in shadow/warn/action modes."""

    from pilot_core.constants import ActivationMode, SessionState, SignalName
    from pilot_core.policy_runtime import run_policy_runtime
    from tests.integration.test_day35_full_signal_integration import (
        FIXTURE_DIR,
        evaluate_all_signals,
        read_jsonl,
    )

    report: dict[str, object] = {}

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        signal_results = evaluate_all_signals(records)

        case_report: dict[str, object] = {}

        for mode in (
            ActivationMode.SHADOW,
            ActivationMode.WARN,
            ActivationMode.ACTION,
        ):
            result = run_policy_runtime(
                signal_results,
                current_state=SessionState.HEALTHY,
                activation_modes={signal: mode for signal in SignalName},
                default_mode=mode,
                at_stop_hook=True,
                turn_index=10,
            )

            case_report[mode.value] = {
                "health_score": round(result.health.health_score, 4),
                "state": result.transition.next_state.value,
                "effective_mode": result.applied_policy.effective_mode.value,
                "policy_action": result.policy_decision.action.value,
                "has_stdout": result.should_emit_stdout,
                "has_stderr": result.should_emit_stderr,
                "should_prepare_handoff": result.policy_decision.should_prepare_handoff,
                "top_signals": [signal.value for signal in result.top_signals],
            }

        report[path.stem] = case_report

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
