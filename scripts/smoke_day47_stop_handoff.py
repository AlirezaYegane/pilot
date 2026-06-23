"""Day 47 stop-hook handoff smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Run stop-hook handoff generation over healthy/degraded replay cases."""

    from pilot_core.constants import ActivationMode, SessionState
    from pilot_core.stop_handoff import build_stop_handoff_result, stop_handoff_summary
    from tests.integration.test_day35_full_signal_integration import (
        FIXTURE_DIR,
        evaluate_all_signals,
        read_jsonl,
    )

    report: dict[str, object] = {}

    for case_name in ("healthy_session", "degraded_session"):
        records = read_jsonl(FIXTURE_DIR / f"{case_name}.jsonl")
        signal_results = evaluate_all_signals(records)

        case_report: dict[str, object] = {}

        for mode in (
            ActivationMode.SHADOW,
            ActivationMode.WARN,
            ActivationMode.ACTION,
        ):
            result = build_stop_handoff_result(
                signal_results,
                records=records,
                session_id=f"smoke-day47-{case_name}-{mode.value}",
                task=f"Continue from {case_name}",
                current_state=SessionState.HEALTHY,
                default_mode=mode,
                at_stop_hook=True,
                write_files=False,
                generated_at="2026-06-23T00:00:00+00:00",
            )

            case_report[mode.value] = stop_handoff_summary(result)

        report[case_name] = case_report

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
