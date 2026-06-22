"""Day 43 handoff schema smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Create, serialise, parse, and summarise a representative handoff."""

    from pilot_core.handoff import (
        HandoffBlocker,
        HandoffBlockerSeverity,
        HandoffDecision,
        HandoffDoNotRedo,
        HandoffFileChange,
        HandoffFileStatus,
        HandoffSchema,
        handoff_from_json,
        handoff_summary,
        handoff_to_json,
    )

    handoff = HandoffSchema(
        session_id="smoke-day43",
        task="Implement Day 43 handoff schema",
        progress=(
            "Created the stable handoff data contract with task, progress, "
            "decisions, files modified, blockers, next step, and do-not-redo."
        ),
        decisions=(
            HandoffDecision(
                title="Keep Day 43 schema-only",
                rationale="Extraction, markdown rendering, and hook integration are later days.",
                alternatives_rejected=("wire stop hook today", "render markdown today"),
            ),
        ),
        files_modified=(
            HandoffFileChange(
                path="pilot_core/handoff.py",
                status=HandoffFileStatus.CREATED,
                reason="core handoff schema",
            ),
            HandoffFileChange(
                path="tests/unit/test_handoff_schema.py",
                status=HandoffFileStatus.CREATED,
                reason="schema contract tests",
            ),
        ),
        blockers=(
            HandoffBlocker(
                description="No DB extractor exists yet",
                severity=HandoffBlockerSeverity.INFO,
                evidence="Day 44 owns summary extraction from DB",
            ),
        ),
        next_step="Implement summary extractor from DB",
        do_not_redo=(
            HandoffDoNotRedo(
                item="Do not generate handoff markdown before renderer day",
                reason="Day 46 owns markdown rendering",
            ),
        ),
        notes=("Smoke test confirms JSON round trip and summary output.",),
    )

    text = handoff_to_json(handoff)
    parsed = handoff_from_json(text)

    report = {
        "summary": handoff_summary(parsed),
        "json_size": len(text),
        "round_trip_equal": parsed == handoff,
        "payload_preview": parsed.to_dict(),
    }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
