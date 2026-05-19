"""Token estimation helpers for Pilot.

PostToolUse needs cheap token estimates for tool inputs and outputs.

The preferred path is tiktoken. If it is missing or fails, Pilot falls back to
a conservative character-based estimate. Token estimation must never break a
hook.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Protocol, cast


class TokenEncoder(Protocol):
    """Small protocol for tokenizer implementations."""

    def encode(self, text: str) -> list[int]:
        """Encode text into token ids."""


def stable_json_dumps(value: object) -> str:
    """Serialize arbitrary values into stable text for hashing/token counting."""

    if isinstance(value, str):
        return value

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        return str(value)


@lru_cache(maxsize=1)
def _get_tiktoken_encoder() -> TokenEncoder | None:
    """Return a cached tiktoken encoder when available."""

    try:
        import tiktoken
    except Exception:
        return None

    try:
        return cast(TokenEncoder, tiktoken.get_encoding("cl100k_base"))
    except Exception:
        return None


def estimate_token_count(value: object) -> int:
    """Estimate token count for a Python value."""

    text = stable_json_dumps(value)

    if not text:
        return 0

    encoder = _get_tiktoken_encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass

    return max(1, (len(text) + 3) // 4)


def payload_size_bytes(value: object) -> int:
    """Return UTF-8 byte size for a serialised payload."""

    return len(stable_json_dumps(value).encode("utf-8"))
