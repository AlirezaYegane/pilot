"""Day 36 health score smoke report.

This script evaluates all eight Pilot signals against replay cases and then
computes the combined health score for each case.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _as_float(value: object) -> float:
    """Return value as float with explicit runtime narrowing."""

    if isinstance(value, int | float):
        return float(value)

    raise TypeError(f"Expected numeric value, got {value!r}")


def _as_int(value: object) -> int:
    """Return value as int with explicit runtime narrowing."""

    if isinstance(value, int):
        return value

    raise TypeError(f"Expected integer value, got {value!r}")


def _as_str(value: object) -> str:
    """Return value as string with explicit runtime narrowing."""

    if isinstance(value, str):
        return value

    raise TypeError(f"Expected string value, got {value!r}")


def _as_list(value: object) -> list[object]:
    """Return value as list with explicit runtime narrowing."""

    if isinstance(value, list):
        return value

    raise TypeError(f"Expected list value, got {value!r}")


def case_verdict(case_name: str, health_score: float, state: str) -> str:
    """Return a compact pass/review verdict for human smoke inspection."""

    if case_name == "healthy_session":
        return "pass" if health_score >= 0.80 and state == "healthy" else "review"

    if case_name in {"noisy_session", "ambiguous_session"}:
        return "pass" if health_score >= 0.40 and state != "critical" else "review"

    if case_name == "degraded_session":
        return "pass" if health_score < 0.60 and state in {"degrading", "critical"} else "review"

    return "review"


def main() -> None:
    """Run the Day 36 smoke report."""

    from pilot_core.health import compute_health_score, health_score_summary
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
        summary = health_score_summary(health)

        state = _as_str(summary["derived_state"])
        score = _as_float(summary["health_score"])
        adjusted_badness = _as_float(summary["adjusted_badness_score"])
        fired_count = _as_int(summary["fired_count"])
        penalty_multiplier = _as_float(summary["penalty_multiplier"])
        top_contributors = _as_list(summary["top_contributors"])[:3]

        report[path.stem] = {
            "health_score": round(score, 4),
            "derived_state": state,
            "fired_count": fired_count,
            "adjusted_badness_score": round(adjusted_badness, 4),
            "penalty_multiplier": penalty_multiplier,
            "top_contributors": top_contributors,
            "verdict": case_verdict(path.stem, score, state),
        }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
