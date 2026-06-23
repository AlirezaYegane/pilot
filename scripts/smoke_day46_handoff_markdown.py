"""Day 46 handoff markdown renderer smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FIXTURE_DIR = Path("tests") / "fixtures" / "replay_cases"


def read_jsonl(path: Path) -> list[dict[str, object]]:
    """Read a JSONL replay fixture."""

    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"Expected JSON object in {path}: {line!r}")

        records.append(cast(dict[str, object], raw))

    return records


def main() -> None:
    """Render representative replay cases into handoff markdown."""

    from pilot_core.handoff import HandoffFileChange, HandoffFileStatus, HandoffSchema
    from pilot_core.handoff_blockers import extract_handoff_blockers
    from pilot_core.render.handoff_md import (
        HandoffMarkdownOptions,
        HandoffMarkdownStyle,
        handoff_markdown_summary,
        render_handoff_markdown,
    )

    report: dict[str, object] = {}

    for case_name in ("healthy_session", "degraded_session"):
        records = read_jsonl(FIXTURE_DIR / f"{case_name}.jsonl")
        extraction = extract_handoff_blockers(records)

        handoff = HandoffSchema(
            session_id=f"smoke-day46-{case_name}",
            task=f"Continue from replay case: {case_name}",
            progress=(
                f"Read {len(records)} replay records and extracted "
                f"{len(extraction.blockers)} blocker(s)."
            ),
            files_modified=(
                HandoffFileChange(
                    path=f"tests/fixtures/replay_cases/{case_name}.jsonl",
                    status=HandoffFileStatus.UNKNOWN,
                    reason="source replay fixture",
                    important=False,
                ),
            ),
            blockers=extraction.blockers,
            next_step="Use this markdown as the next-session handoff context.",
            do_not_redo=extraction.do_not_redo,
            notes=(extraction.explanation,),
        )

        markdown = render_handoff_markdown(
            handoff,
            options=HandoffMarkdownOptions(style=HandoffMarkdownStyle.FULL),
        )

        report[case_name] = {
            "summary": handoff_markdown_summary(handoff, markdown=markdown),
            "preview": markdown.splitlines()[:18],
        }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
