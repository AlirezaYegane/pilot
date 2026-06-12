"""Day 41 action policy smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from pilot_core.action_policy import action_policy_summary, apply_action_policy
    from pilot_core.constants import ActivationMode, SessionState, SignalName
    from pilot_core.decision_engine import decide_next_action
    from pilot_core.health import compute_health_score
    from pilot_core.state_machine import transition_from_health_with_hysteresis
    from pilot_core.warnings import (
        render_claude_additional_context,
        render_hook_stdout_payload,
        render_user_stderr,
    )
    from tests.integration.test_day35_full_signal_integration import (
        FIXTURE_DIR,
        evaluate_all_signals,
        read_jsonl,
    )

    report: dict[str, object] = {}

    mode_maps = {
        "shadow": {signal: ActivationMode.SHADOW for signal in SignalName},
        "warn": {signal: ActivationMode.WARN for signal in SignalName},
        "action": {signal: ActivationMode.ACTION for signal in SignalName},
    }

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

        case_report: dict[str, object] = {
            "health_score": round(health.health_score, 4),
            "state": transition.next_state.value,
            "base_action": decision.action.value,
        }

        for mode_name, activation_modes in mode_maps.items():
            result = apply_action_policy(
                decision,
                health=health,
                activation_modes=activation_modes,
            )
            policy_decision = result.policy_decision

            additional_context = render_claude_additional_context(policy_decision)
            stderr_text = render_user_stderr(policy_decision)
            payload = render_hook_stdout_payload(policy_decision)

            case_report[mode_name] = {
                "summary": action_policy_summary(result),
                "payload": payload,
                "additional_context_preview": (
                    additional_context[:120] if additional_context is not None else None
                ),
                "stderr_preview": stderr_text[:120] if stderr_text is not None else None,
            }

        report[path.stem] = case_report

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
