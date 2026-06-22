"""Day 45 handoff blocker extraction smoke report."""

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
    """Run blocker extraction over replay fixtures."""

    from pilot_core.handoff_blockers import (
        extract_handoff_blockers,
        handoff_blocker_extraction_summary,
    )

    report: dict[str, object] = {}

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        result = extract_handoff_blockers(records)
        report[path.stem] = handoff_blocker_extraction_summary(result)

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
