"""Day 51 budget usage smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "replay_cases"


def read_jsonl(path: Path) -> list[dict[str, object]]:
    """Read a JSONL fixture."""

    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        assert isinstance(raw, dict)
        records.append(cast(dict[str, object], raw))

    return records


def case_int(records: list[dict[str, object]], key: str, default: int) -> int:
    """Return max integer value for a key."""

    values: list[int] = []

    for record in records:
        value = record.get(key)
        if isinstance(value, int):
            values.append(value)

    return max(values) if values else default


def main() -> None:
    """Run Day 51 budget report over replay cases."""

    from pilot_core.budget import budget_report_summary, build_budget_report

    report: dict[str, object] = {}

    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        now_ms = case_int(records, "timestamp_ms", 0)
        current_used_tokens = case_int(records, "current_used_tokens", 0)

        budget = build_budget_report(
            records,
            now_ms=now_ms,
            current_used_tokens=current_used_tokens,
            plan_cap_tokens=250_000_000,
            daily_budget_tokens=5_000_000,
            weekly_budget_tokens=30_000_000,
        )

        report[path.stem] = budget_report_summary(budget)

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
