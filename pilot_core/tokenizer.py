"""Tokenizer and cost estimation helpers for Pilot.

Day 50 starts the Budget + CLI foundation.

This module owns:
- safe stringification for arbitrary hook payloads
- lightweight token estimation with optional tiktoken support
- deterministic fallback estimation when tiktoken is unavailable
- cost estimation from explicit model pricing

Important:
- cost helpers are estimates, not billing authority
- pass explicit pricing when exact billing math is needed
- helpers are pure and side-effect free
"""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

DEFAULT_ENCODING_NAME = "cl100k_base"
DEFAULT_APPROX_CHARS_PER_TOKEN = 4.0
DEFAULT_MAX_STRINGIFY_CHARS = 50_000
TRUNCATION_SUFFIX = "... [truncated]"


class TokenizerBackend(str, Enum):
    """Tokenizer backend used for a token estimate."""

    TIKTOKEN = "tiktoken"
    APPROXIMATE = "approximate"


@dataclass(frozen=True)
class StringifiedPayload:
    """Safely stringified payload with metadata."""

    text: str
    original_type: str
    char_count: int
    was_truncated: bool
    max_chars: int

    @property
    def is_empty(self) -> bool:
        """Return True when the stringified payload is empty."""

        return self.text == ""


@dataclass(frozen=True)
class TextTokenEstimate:
    """Token estimate for one stringified text payload."""

    token_count: int
    char_count: int
    backend: TokenizerBackend
    encoding_name: str
    was_truncated: bool
    approximate: bool
    explanation: str


@dataclass(frozen=True)
class PayloadTokenEstimate:
    """Token estimate for a tool input/output style payload."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_chars: int
    output_chars: int
    backend: TokenizerBackend
    encoding_name: str
    input_was_truncated: bool
    output_was_truncated: bool
    approximate: bool
    explanation: str


@dataclass(frozen=True)
class ModelPricing:
    """USD pricing per one million input/output tokens."""

    model_name: str
    input_usd_per_million_tokens: float
    output_usd_per_million_tokens: float


@dataclass(frozen=True)
class TokenCostEstimate:
    """Estimated token cost in USD."""

    model_name: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float

    @property
    def total_tokens(self) -> int:
        """Return input + output tokens."""

        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class TokenTotals:
    """Aggregated token totals across multiple estimates."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    record_count: int
    approximate_count: int


ZERO_PRICE_MODEL = ModelPricing(
    model_name="unpriced",
    input_usd_per_million_tokens=0.0,
    output_usd_per_million_tokens=0.0,
)


def _validate_max_chars(max_chars: int) -> None:
    """Validate bounded-string size."""

    if max_chars < len(TRUNCATION_SUFFIX) + 1:
        raise ValueError("max_chars is too small to include truncation suffix")


def _json_default(value: object) -> object:
    """JSON fallback for values that are not directly serialisable."""

    if isinstance(value, set | frozenset):
        return sorted(str(item) for item in value)

    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("utf-8", errors="replace")

    return repr(value)


def _truncate_text(text: str, *, max_chars: int) -> tuple[str, bool]:
    """Return text bounded to max_chars."""

    _validate_max_chars(max_chars)

    if len(text) <= max_chars:
        return text, False

    keep_chars = max_chars - len(TRUNCATION_SUFFIX)
    return text[:keep_chars] + TRUNCATION_SUFFIX, True


def stringify_payload(
    value: object,
    *,
    max_chars: int = DEFAULT_MAX_STRINGIFY_CHARS,
) -> StringifiedPayload:
    """Safely stringify any payload without raising for normal hook data.

    The output is deterministic for JSON-compatible mappings/sequences.
    """

    original_type = type(value).__name__

    if value is None:
        raw_text = ""
    elif isinstance(value, str):
        raw_text = value
    elif isinstance(value, bytes | bytearray):
        raw_text = bytes(value).decode("utf-8", errors="replace")
    else:
        try:
            raw_text = json.dumps(
                value,
                default=_json_default,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError, OverflowError):
            raw_text = repr(value)

    bounded, was_truncated = _truncate_text(raw_text, max_chars=max_chars)

    return StringifiedPayload(
        text=bounded,
        original_type=original_type,
        char_count=len(bounded),
        was_truncated=was_truncated,
        max_chars=max_chars,
    )


def safe_stringify(
    value: object,
    *,
    max_chars: int = DEFAULT_MAX_STRINGIFY_CHARS,
) -> str:
    """Return only the safe string form of a payload."""

    return stringify_payload(value, max_chars=max_chars).text


def approximate_token_count(
    text: str,
    *,
    chars_per_token: float = DEFAULT_APPROX_CHARS_PER_TOKEN,
) -> int:
    """Estimate token count from character length."""

    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be greater than zero")

    if text == "":
        return 0

    return math.ceil(len(text) / chars_per_token)


def _load_tiktoken_encoding(encoding_name: str) -> tuple[Any | None, str | None]:
    """Load a tiktoken encoding, returning an error string instead of raising."""

    try:
        tiktoken = importlib.import_module("tiktoken")
        encoding = tiktoken.get_encoding(encoding_name)
        return encoding, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def estimate_text_tokens(
    value: object,
    *,
    encoding_name: str = DEFAULT_ENCODING_NAME,
    use_tiktoken: bool = True,
    max_chars: int = DEFAULT_MAX_STRINGIFY_CHARS,
    chars_per_token: float = DEFAULT_APPROX_CHARS_PER_TOKEN,
) -> TextTokenEstimate:
    """Estimate tokens for one arbitrary payload."""

    stringified = stringify_payload(value, max_chars=max_chars)

    if use_tiktoken:
        encoding, error = _load_tiktoken_encoding(encoding_name)
        if encoding is not None:
            token_count = len(encoding.encode(stringified.text))
            return TextTokenEstimate(
                token_count=token_count,
                char_count=stringified.char_count,
                backend=TokenizerBackend.TIKTOKEN,
                encoding_name=encoding_name,
                was_truncated=stringified.was_truncated,
                approximate=False,
                explanation=f"Tokenized with tiktoken encoding {encoding_name}.",
            )

        fallback_count = approximate_token_count(
            stringified.text,
            chars_per_token=chars_per_token,
        )
        return TextTokenEstimate(
            token_count=fallback_count,
            char_count=stringified.char_count,
            backend=TokenizerBackend.APPROXIMATE,
            encoding_name=encoding_name,
            was_truncated=stringified.was_truncated,
            approximate=True,
            explanation=f"Used approximate token estimate because tiktoken was unavailable: {error}",
        )

    fallback_count = approximate_token_count(
        stringified.text,
        chars_per_token=chars_per_token,
    )
    return TextTokenEstimate(
        token_count=fallback_count,
        char_count=stringified.char_count,
        backend=TokenizerBackend.APPROXIMATE,
        encoding_name=encoding_name,
        was_truncated=stringified.was_truncated,
        approximate=True,
        explanation="Used approximate token estimate by request.",
    )


def estimate_payload_tokens(
    tool_input: object,
    tool_response: object = None,
    *,
    encoding_name: str = DEFAULT_ENCODING_NAME,
    use_tiktoken: bool = True,
    max_chars: int = DEFAULT_MAX_STRINGIFY_CHARS,
    chars_per_token: float = DEFAULT_APPROX_CHARS_PER_TOKEN,
) -> PayloadTokenEstimate:
    """Estimate input/output tokens for a tool-call style payload."""

    input_estimate = estimate_text_tokens(
        tool_input,
        encoding_name=encoding_name,
        use_tiktoken=use_tiktoken,
        max_chars=max_chars,
        chars_per_token=chars_per_token,
    )
    output_estimate = estimate_text_tokens(
        tool_response,
        encoding_name=encoding_name,
        use_tiktoken=use_tiktoken,
        max_chars=max_chars,
        chars_per_token=chars_per_token,
    )

    backend = (
        TokenizerBackend.TIKTOKEN
        if input_estimate.backend is TokenizerBackend.TIKTOKEN
        and output_estimate.backend is TokenizerBackend.TIKTOKEN
        else TokenizerBackend.APPROXIMATE
    )

    approximate = input_estimate.approximate or output_estimate.approximate

    return PayloadTokenEstimate(
        input_tokens=input_estimate.token_count,
        output_tokens=output_estimate.token_count,
        total_tokens=input_estimate.token_count + output_estimate.token_count,
        input_chars=input_estimate.char_count,
        output_chars=output_estimate.char_count,
        backend=backend,
        encoding_name=encoding_name,
        input_was_truncated=input_estimate.was_truncated,
        output_was_truncated=output_estimate.was_truncated,
        approximate=approximate,
        explanation=(
            "Estimated payload tokens using "
            f"{backend.value}; input={input_estimate.token_count}, "
            f"output={output_estimate.token_count}."
        ),
    )


def _first_present_value(
    record: Mapping[str, object],
    keys: Sequence[str],
) -> object:
    """Return the first present record value from keys."""

    for key in keys:
        if key in record:
            return record[key]

    return None


def estimate_record_tokens(
    record: Mapping[str, object],
    *,
    input_keys: Sequence[str] = ("tool_input", "input", "prompt"),
    output_keys: Sequence[str] = ("tool_response", "response", "output", "text"),
    encoding_name: str = DEFAULT_ENCODING_NAME,
    use_tiktoken: bool = True,
    max_chars: int = DEFAULT_MAX_STRINGIFY_CHARS,
) -> PayloadTokenEstimate:
    """Estimate tokens for a replay/hook record."""

    return estimate_payload_tokens(
        _first_present_value(record, input_keys),
        _first_present_value(record, output_keys),
        encoding_name=encoding_name,
        use_tiktoken=use_tiktoken,
        max_chars=max_chars,
    )


def sum_payload_estimates(estimates: Sequence[PayloadTokenEstimate]) -> TokenTotals:
    """Aggregate token estimates."""

    input_tokens = sum(estimate.input_tokens for estimate in estimates)
    output_tokens = sum(estimate.output_tokens for estimate in estimates)
    approximate_count = sum(1 for estimate in estimates if estimate.approximate)

    return TokenTotals(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        record_count=len(estimates),
        approximate_count=approximate_count,
    )


def estimate_records_tokens(
    records: Sequence[Mapping[str, object]],
    *,
    encoding_name: str = DEFAULT_ENCODING_NAME,
    use_tiktoken: bool = True,
    max_chars: int = DEFAULT_MAX_STRINGIFY_CHARS,
) -> TokenTotals:
    """Estimate token totals for many replay/hook records."""

    estimates = [
        estimate_record_tokens(
            record,
            encoding_name=encoding_name,
            use_tiktoken=use_tiktoken,
            max_chars=max_chars,
        )
        for record in records
    ]
    return sum_payload_estimates(estimates)


def tokens_to_usd(tokens: int, usd_per_million_tokens: float) -> float:
    """Convert token count to estimated USD cost."""

    if tokens < 0:
        raise ValueError("tokens must be non-negative")

    if usd_per_million_tokens < 0:
        raise ValueError("usd_per_million_tokens must be non-negative")

    return (tokens / 1_000_000) * usd_per_million_tokens


def estimate_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    pricing: ModelPricing = ZERO_PRICE_MODEL,
) -> TokenCostEstimate:
    """Estimate USD cost from token counts and explicit pricing."""

    input_cost = tokens_to_usd(input_tokens, pricing.input_usd_per_million_tokens)
    output_cost = tokens_to_usd(output_tokens, pricing.output_usd_per_million_tokens)

    return TokenCostEstimate(
        model_name=pricing.model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=input_cost + output_cost,
    )


def estimate_payload_cost(
    estimate: PayloadTokenEstimate | TokenTotals,
    *,
    pricing: ModelPricing = ZERO_PRICE_MODEL,
) -> TokenCostEstimate:
    """Estimate cost from a payload or aggregate token estimate."""

    return estimate_cost(
        input_tokens=estimate.input_tokens,
        output_tokens=estimate.output_tokens,
        pricing=pricing,
    )


def token_estimate_summary(estimate: PayloadTokenEstimate | TokenTotals) -> dict[str, object]:
    """Return a serialisable token estimate summary."""

    summary: dict[str, object] = {
        "input_tokens": estimate.input_tokens,
        "output_tokens": estimate.output_tokens,
        "total_tokens": estimate.total_tokens,
    }

    if isinstance(estimate, PayloadTokenEstimate):
        summary.update(
            {
                "backend": estimate.backend.value,
                "encoding_name": estimate.encoding_name,
                "approximate": estimate.approximate,
                "input_was_truncated": estimate.input_was_truncated,
                "output_was_truncated": estimate.output_was_truncated,
            }
        )
    else:
        summary.update(
            {
                "record_count": estimate.record_count,
                "approximate_count": estimate.approximate_count,
            }
        )

    return summary


def cost_estimate_summary(estimate: TokenCostEstimate) -> dict[str, object]:
    """Return a serialisable cost estimate summary."""

    return {
        "model_name": estimate.model_name,
        "input_tokens": estimate.input_tokens,
        "output_tokens": estimate.output_tokens,
        "total_tokens": estimate.total_tokens,
        "input_cost_usd": round(estimate.input_cost_usd, 8),
        "output_cost_usd": round(estimate.output_cost_usd, 8),
        "total_cost_usd": round(estimate.total_cost_usd, 8),
    }
