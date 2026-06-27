from __future__ import annotations

import json
from pathlib import Path

from pilot_core.tokenizer import (
    ModelPricing,
    cost_estimate_summary,
    estimate_payload_cost,
    estimate_record_tokens,
    estimate_records_tokens,
    token_estimate_summary,
)

FIXTURE_DIR = Path("tests") / "fixtures" / "replay_cases"


def read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise TypeError(f"Expected JSON object in {path}")

        records.append(raw)

    return records


def test_day50_estimates_tokens_for_all_replay_cases() -> None:
    for path in sorted(FIXTURE_DIR.glob("*.jsonl")):
        records = read_jsonl(path)
        totals = estimate_records_tokens(records, use_tiktoken=False)

        assert totals.record_count == len(records)
        assert totals.total_tokens > 0
        assert totals.input_tokens >= 0
        assert totals.output_tokens >= 0
        assert totals.approximate_count == len(records)


def test_day50_record_estimates_are_safe_for_replay_payload_shapes() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")

    estimates = [
        estimate_record_tokens(record, use_tiktoken=False, max_chars=2_000) for record in records
    ]

    assert all(estimate.total_tokens >= 0 for estimate in estimates)
    assert any(estimate.input_tokens > 0 for estimate in estimates)
    assert any(estimate.output_tokens > 0 for estimate in estimates)


def test_day50_cost_estimates_can_be_built_from_fixture_totals() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    totals = estimate_records_tokens(records, use_tiktoken=False)
    pricing = ModelPricing(
        model_name="test-sonnet-like",
        input_usd_per_million_tokens=3.0,
        output_usd_per_million_tokens=15.0,
    )

    cost = estimate_payload_cost(totals, pricing=pricing)
    summary = cost_estimate_summary(cost)

    assert cost.total_tokens == totals.total_tokens
    assert cost.total_cost_usd > 0
    assert summary["model_name"] == "test-sonnet-like"


def test_day50_token_summary_for_fixture_totals_is_serialisable() -> None:
    records = read_jsonl(FIXTURE_DIR / "healthy_session.jsonl")
    totals = estimate_records_tokens(records, use_tiktoken=False)

    summary = token_estimate_summary(totals)

    assert summary["record_count"] == len(records)
    assert summary["total_tokens"] == totals.total_tokens
    assert summary["approximate_count"] == len(records)
