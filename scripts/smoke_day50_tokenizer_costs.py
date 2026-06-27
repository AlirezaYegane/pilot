"""Day 50 tokenizer and cost estimation smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_jsonl(path: Path) -> list[dict[str, object]]:
    """Read JSONL records for smoke reporting."""

    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise TypeError(f"Expected JSON object in {path}")

        records.append(raw)

    return records


def main() -> None:
    """Print Day 50 smoke report."""

    from pilot_core.tokenizer import (
        ModelPricing,
        cost_estimate_summary,
        estimate_payload_cost,
        estimate_payload_tokens,
        estimate_records_tokens,
        safe_stringify,
        token_estimate_summary,
    )

    fixture_dir = Path("tests") / "fixtures" / "replay_cases"
    pricing = ModelPricing(
        model_name="smoke-test-model",
        input_usd_per_million_tokens=3.0,
        output_usd_per_million_tokens=15.0,
    )

    sample_payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest"},
        "tool_response": {"stdout": "500 passed"},
    }

    sample_estimate = estimate_payload_tokens(
        sample_payload["tool_input"],
        sample_payload["tool_response"],
        use_tiktoken=False,
    )
    sample_cost = estimate_payload_cost(sample_estimate, pricing=pricing)

    report: dict[str, object] = {
        "sample_safe_stringify": safe_stringify(sample_payload),
        "sample_tokens": token_estimate_summary(sample_estimate),
        "sample_cost": cost_estimate_summary(sample_cost),
        "fixtures": {},
    }

    fixture_report: dict[str, object] = {}

    for path in sorted(fixture_dir.glob("*.jsonl")):
        records = read_jsonl(path)
        totals = estimate_records_tokens(records, use_tiktoken=False)
        cost = estimate_payload_cost(totals, pricing=pricing)

        fixture_report[path.stem] = {
            "token_totals": token_estimate_summary(totals),
            "cost": cost_estimate_summary(cost),
        }

    report["fixtures"] = fixture_report

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
