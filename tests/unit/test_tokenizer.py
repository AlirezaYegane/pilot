from __future__ import annotations

import pytest

from pilot_core.tokenizer import (
    ModelPricing,
    TokenizerBackend,
    approximate_token_count,
    cost_estimate_summary,
    estimate_cost,
    estimate_payload_cost,
    estimate_payload_tokens,
    estimate_record_tokens,
    estimate_records_tokens,
    estimate_text_tokens,
    safe_stringify,
    stringify_payload,
    token_estimate_summary,
    tokens_to_usd,
)


def test_safe_stringify_mapping_is_deterministic() -> None:
    payload = {"b": 2, "a": 1}

    assert safe_stringify(payload) == '{"a":1,"b":2}'


def test_safe_stringify_handles_bytes_with_replacement() -> None:
    text = safe_stringify(b"hello-\xff")

    assert "hello-" in text
    assert "\ufffd" in text


def test_safe_stringify_falls_back_for_circular_payload() -> None:
    payload: dict[str, object] = {}
    payload["self"] = payload

    text = safe_stringify(payload)

    assert "self" in text
    assert "{...}" in text


def test_stringify_payload_truncates_safely() -> None:
    result = stringify_payload("x" * 200, max_chars=40)

    assert result.was_truncated
    assert len(result.text) == 40
    assert result.text.endswith("... [truncated]")


def test_stringify_payload_rejects_tiny_bounds() -> None:
    with pytest.raises(ValueError, match="max_chars"):
        stringify_payload("hello", max_chars=5)


def test_approximate_token_count_is_deterministic() -> None:
    assert approximate_token_count("") == 0
    assert approximate_token_count("abcd", chars_per_token=4.0) == 1
    assert approximate_token_count("abcde", chars_per_token=4.0) == 2


def test_estimate_text_tokens_can_force_approximate_backend() -> None:
    estimate = estimate_text_tokens("abcdefgh", use_tiktoken=False, chars_per_token=4.0)

    assert estimate.token_count == 2
    assert estimate.backend is TokenizerBackend.APPROXIMATE
    assert estimate.approximate


def test_estimate_text_tokens_falls_back_for_unknown_encoding() -> None:
    estimate = estimate_text_tokens(
        "hello world",
        encoding_name="not-a-real-encoding",
        use_tiktoken=True,
    )

    assert estimate.token_count >= 1
    assert estimate.backend is TokenizerBackend.APPROXIMATE
    assert estimate.approximate


def test_estimate_payload_tokens_combines_input_and_output() -> None:
    estimate = estimate_payload_tokens(
        {"command": "pytest"},
        {"stdout": "passed"},
        use_tiktoken=False,
        chars_per_token=4.0,
    )

    assert estimate.input_tokens > 0
    assert estimate.output_tokens > 0
    assert estimate.total_tokens == estimate.input_tokens + estimate.output_tokens
    assert estimate.backend is TokenizerBackend.APPROXIMATE


def test_estimate_record_tokens_uses_replay_shape() -> None:
    estimate = estimate_record_tokens(
        {
            "tool_input": {"file_path": "pilot_core/tokenizer.py"},
            "text": "Implemented tokenizer helpers.",
        },
        use_tiktoken=False,
    )

    assert estimate.total_tokens > 0


def test_estimate_records_tokens_aggregates_many_records() -> None:
    totals = estimate_records_tokens(
        (
            {"tool_input": {"a": 1}, "text": "first"},
            {"tool_input": {"b": 2}, "text": "second"},
        ),
        use_tiktoken=False,
    )

    assert totals.record_count == 2
    assert totals.total_tokens == totals.input_tokens + totals.output_tokens
    assert totals.approximate_count == 2


def test_tokens_to_usd_uses_per_million_pricing() -> None:
    assert tokens_to_usd(1_000_000, 3.0) == 3.0
    assert tokens_to_usd(500_000, 4.0) == 2.0


def test_tokens_to_usd_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        tokens_to_usd(-1, 1.0)

    with pytest.raises(ValueError, match="non-negative"):
        tokens_to_usd(1, -1.0)


def test_estimate_cost_with_explicit_pricing() -> None:
    pricing = ModelPricing(
        model_name="test-model",
        input_usd_per_million_tokens=3.0,
        output_usd_per_million_tokens=15.0,
    )

    estimate = estimate_cost(
        input_tokens=1_000_000,
        output_tokens=2_000_000,
        pricing=pricing,
    )

    assert estimate.model_name == "test-model"
    assert estimate.input_cost_usd == 3.0
    assert estimate.output_cost_usd == 30.0
    assert estimate.total_cost_usd == 33.0


def test_estimate_payload_cost_from_payload_estimate() -> None:
    payload = estimate_payload_tokens("abcd", "abcdefgh", use_tiktoken=False)
    pricing = ModelPricing(
        model_name="test-model",
        input_usd_per_million_tokens=1.0,
        output_usd_per_million_tokens=2.0,
    )

    cost = estimate_payload_cost(payload, pricing=pricing)

    assert cost.input_tokens == payload.input_tokens
    assert cost.output_tokens == payload.output_tokens
    assert cost.total_cost_usd > 0


def test_summary_helpers_are_serialisable() -> None:
    payload = estimate_payload_tokens("hello", "world", use_tiktoken=False)
    pricing = ModelPricing(
        model_name="test-model",
        input_usd_per_million_tokens=1.0,
        output_usd_per_million_tokens=2.0,
    )
    cost = estimate_payload_cost(payload, pricing=pricing)

    token_summary = token_estimate_summary(payload)
    cost_summary = cost_estimate_summary(cost)

    assert token_summary["total_tokens"] == payload.total_tokens
    assert token_summary["backend"] == "approximate"
    assert cost_summary["model_name"] == "test-model"
    assert "total_cost_usd" in cost_summary
