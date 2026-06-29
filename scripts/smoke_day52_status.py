"""Day 52 pilot status smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "replay_cases"


def main() -> None:
    """Run status rendering over replay cases."""

    from pilot_core.render.status import render_status_snapshot
    from pilot_core.status import (
        build_status_snapshot_from_records,
        read_jsonl_records,
        status_snapshot_summary,
    )

    report: dict[str, object] = {}
    degraded_text = ""

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl_records(path)
        snapshot = build_status_snapshot_from_records(records, session_id=path.stem)
        report[path.stem] = status_snapshot_summary(snapshot)

        if path.stem == "degraded_session":
            degraded_text = render_status_snapshot(snapshot)

    print(json.dumps(report, indent=2, sort_keys=True))
    print()
    print(degraded_text, end="")


if __name__ == "__main__":
    main()
