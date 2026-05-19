"""Fast PreToolUse policy checks.

PreToolUse is synchronous, so this module must stay intentionally lightweight:
- parse hook payloads
- compute a stable tool-input fingerprint
- do small read-only SQLite checks
- return a safe stdout payload for the hook

Heavy signal evaluation belongs in PostToolUse, not here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pilot_core.constants import SessionState
from pilot_core.paths import resolve_runtime_paths
from pilot_core.safety import log_exception


@dataclass(frozen=True)
class PreToolUsePayload:
    """Normalised PreToolUse hook payload."""

    session_id: str
    tool_name: str
    tool_input: object
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class PreToolSnapshot:
    """Tiny read-only snapshot used by the PreToolUse policy."""

    session_state: str | None = None
    recent_same_input_count: int = 0


@dataclass(frozen=True)
class PreToolDecision:
    """Decision returned by the PreToolUse policy."""

    allowed: bool
    reason: str = ""
    additional_context: str = ""

    @classmethod
    def allow(cls, additional_context: str = "") -> PreToolDecision:
        """Allow the tool call, optionally adding Claude-facing context."""

        return cls(allowed=True, additional_context=additional_context)

    @classmethod
    def block(cls, reason: str) -> PreToolDecision:
        """Block the tool call.

        This is intentionally opt-in at the hook layer. Pilot defaults to
        non-blocking behaviour unless emergency blocking is explicitly enabled.
        """

        return cls(allowed=False, reason=reason)

    def to_hook_stdout(self) -> dict[str, str]:
        """Render the JSON object that may be printed to stdout by the hook."""

        if not self.allowed:
            return {
                "decision": "block",
                "reason": self.reason or "Pilot blocked this tool call.",
            }

        if self.additional_context:
            return {"additionalContext": self.additional_context}

        return {}


def _first_non_empty(*values: object) -> str:
    """Return the first non-empty string representation from values."""

    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _mapping(value: object) -> Mapping[str, Any] | None:
    """Return value if it is mapping-like."""

    if isinstance(value, Mapping):
        return value
    return None


def parse_pre_tool_payload(payload: Mapping[str, Any]) -> PreToolUsePayload:
    """Normalise likely Claude Code PreToolUse payload shapes."""

    tool = _mapping(payload.get("tool")) or {}

    session_id = _first_non_empty(
        payload.get("session_id"),
        payload.get("sessionId"),
        payload.get("conversation_id"),
        payload.get("conversationId"),
    )
    tool_name = _first_non_empty(
        payload.get("tool_name"),
        payload.get("toolName"),
        payload.get("name"),
        tool.get("name"),
    )

    tool_input: object = {}
    for key in ("tool_input", "toolInput", "input", "arguments"):
        if key in payload:
            tool_input = payload[key]
            break
    else:
        if "input" in tool:
            tool_input = tool["input"]

    return PreToolUsePayload(
        session_id=session_id,
        tool_name=tool_name,
        tool_input=tool_input,
        raw=payload,
    )


def stable_tool_input_hash(tool_name: str, tool_input: object) -> str:
    """Return a stable SHA-256 fingerprint for a tool name and input payload."""

    payload = {
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_session_state(connection: sqlite3.Connection, session_id: str) -> str | None:
    """Read the current session state if the sessions table exists."""

    row = connection.execute(
        "SELECT state FROM sessions WHERE id = ? LIMIT 1;",
        (session_id,),
    ).fetchone()

    if row is None or row[0] is None:
        return None

    return str(row[0])


def _read_recent_same_input_count(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    input_hash: str,
    recent_limit: int,
) -> int:
    """Count matching input hashes in the recent tool-use window."""

    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT input_hash
            FROM tool_uses
            WHERE session_id = ?
            ORDER BY timestamp_ms DESC, id DESC
            LIMIT ?
        )
        WHERE input_hash = ?;
        """,
        (session_id, recent_limit, input_hash),
    ).fetchone()

    if row is None or row[0] is None:
        return 0

    return int(row[0])


def read_pre_tool_snapshot(
    *,
    session_id: str,
    input_hash: str,
    db_path: Path | None = None,
    recent_limit: int = 10,
) -> PreToolSnapshot:
    """Read a tiny snapshot from SQLite without mutating runtime state."""

    resolved_db_path = db_path or resolve_runtime_paths().db_path

    if not session_id or not resolved_db_path.exists():
        return PreToolSnapshot()

    try:
        connection = sqlite3.connect(str(resolved_db_path), timeout=0.05)
        try:
            session_state = _read_session_state(connection, session_id)
            recent_same_input_count = _read_recent_same_input_count(
                connection,
                session_id=session_id,
                input_hash=input_hash,
                recent_limit=recent_limit,
            )
            return PreToolSnapshot(
                session_state=session_state,
                recent_same_input_count=recent_same_input_count,
            )
        finally:
            connection.close()
    except Exception as exc:
        log_exception(exc, context="pre_tool_use_snapshot")
        return PreToolSnapshot()


def evaluate_pre_tool_policy(
    payload: Mapping[str, Any],
    *,
    db_path: Path | None = None,
    block_on_handoff: bool = False,
    repeat_warn_threshold: int = 3,
) -> PreToolDecision:
    """Evaluate a PreToolUse payload and return a safe decision."""

    parsed = parse_pre_tool_payload(payload)

    if not parsed.session_id or not parsed.tool_name:
        return PreToolDecision.allow()

    input_hash = stable_tool_input_hash(parsed.tool_name, parsed.tool_input)
    snapshot = read_pre_tool_snapshot(
        session_id=parsed.session_id,
        input_hash=input_hash,
        db_path=db_path,
    )

    if block_on_handoff and snapshot.session_state in {
        SessionState.HANDOFF_PENDING.value,
        SessionState.HANDED_OFF.value,
    }:
        return PreToolDecision.block(
            "Pilot detected that this session is already in handoff state. "
            "Start or resume from the handoff before running more tools."
        )

    if snapshot.recent_same_input_count >= repeat_warn_threshold:
        return PreToolDecision.allow(
            "Pilot noticed this exact tool call/input has repeated several "
            "times recently. Check whether the session is looping before "
            "continuing."
        )

    return PreToolDecision.allow()


__all__ = [
    "PreToolDecision",
    "PreToolSnapshot",
    "PreToolUsePayload",
    "evaluate_pre_tool_policy",
    "parse_pre_tool_payload",
    "read_pre_tool_snapshot",
    "stable_tool_input_hash",
]
