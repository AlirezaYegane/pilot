"""Stop-hook handoff generation adapter for Pilot.

Day 47 connects the handoff engine to the Stop hook.

Pipeline:
- Stop hook payload / stored signal results
- policy runtime decides whether handoff is allowed
- blocker extractor enriches handoff content from recent records
- markdown renderer creates readable handoff text
- optional writer persists markdown + JSON artifacts

The public functions are written to be testable without Claude Code:
- build_stop_handoff_result()
- generate_stop_handoff_from_payload()
- stop_handoff_summary()
- main()

The hook entrypoint must remain fail-silent. Any exception in main() returns 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from pilot_core.constants import ActivationMode, SessionState
from pilot_core.handoff import (
    HandoffFileChange,
    HandoffFileStatus,
    HandoffSchema,
    handoff_to_json,
)
from pilot_core.handoff_blockers import extract_handoff_blockers
from pilot_core.policy_runtime import PolicyRuntimeResult, run_policy_runtime
from pilot_core.render.handoff_md import (
    HandoffMarkdownOptions,
    HandoffMarkdownStyle,
    handoff_markdown_summary,
    render_handoff_markdown,
)

DEFAULT_STOP_HANDOFF_DIR = ".pilot/handoffs"
DEFAULT_MAX_FILE_CHANGES = 8


RawRecord = Mapping[str, object]


@dataclass(frozen=True)
class StopHandoffResult:
    """Result returned by the stop-hook handoff adapter."""

    runtime: PolicyRuntimeResult
    handoff: HandoffSchema | None
    markdown: str | None
    markdown_path: Path | None
    json_path: Path | None
    hook_payload: dict[str, str]
    user_stderr: str | None
    reason: str

    @property
    def should_generate_handoff(self) -> bool:
        """Return True when a handoff was generated."""

        return self.handoff is not None and self.markdown is not None

    @property
    def should_emit_stdout(self) -> bool:
        """Return True when hook stdout should emit JSON."""

        return bool(self.hook_payload)

    @property
    def should_emit_stderr(self) -> bool:
        """Return True when hook stderr should emit text."""

        return self.user_stderr is not None and self.user_stderr.strip() != ""


def _utc_now() -> str:
    """Return current UTC timestamp in ISO format."""

    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str | None, *, default: str = "session") -> str:
    """Return a filesystem-safe slug."""

    text = (value or default).strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-._")
    return text or default


def _record_get(raw: object, key: str, default: object = None) -> object:
    """Read a value from a mapping-like or object-like record."""

    if isinstance(raw, Mapping):
        return raw.get(key, default)

    return getattr(raw, key, default)


def _as_record_sequence(value: object) -> tuple[RawRecord, ...]:
    """Return mapping records from a payload value."""

    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return tuple()

    records: list[RawRecord] = []

    for item in value:
        if isinstance(item, Mapping):
            records.append(cast(RawRecord, item))

    return tuple(records)


def _extract_records(payload: Mapping[str, object]) -> tuple[RawRecord, ...]:
    """Extract raw session records from common stop-hook/test payload shapes."""

    for key in ("records", "events", "replay_records", "session_records"):
        records = _as_record_sequence(payload.get(key))
        if records:
            return records

    pilot_value = payload.get("pilot")
    if isinstance(pilot_value, Mapping):
        return _extract_records(cast(Mapping[str, object], pilot_value))

    return tuple()


def _extract_signal_results(payload: Mapping[str, object]) -> tuple[object, ...]:
    """Extract signal result payloads from common shapes."""

    for key in ("signal_results", "signals", "signal_outputs"):
        raw = payload.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, str | bytes | bytearray):
            return tuple(raw)

    pilot_value = payload.get("pilot")
    if isinstance(pilot_value, Mapping):
        return _extract_signal_results(cast(Mapping[str, object], pilot_value))

    return tuple()


def _as_bool(value: object, *, default: bool = False) -> bool:
    """Parse a permissive boolean value."""

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False

    return default


def _as_str_or_none(value: object) -> str | None:
    """Return a stripped string or None."""

    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _normalise_state(
    value: object, *, default: SessionState = SessionState.HEALTHY
) -> SessionState:
    """Normalise session state from payload value."""

    if isinstance(value, SessionState):
        return value

    if isinstance(value, str):
        try:
            return SessionState(value)
        except ValueError:
            return default

    return default


def _extract_file_path(raw: RawRecord) -> str | None:
    """Extract a file path from common tool/replay record shapes."""

    for key in ("file_path", "path", "filepath", "target_file"):
        value = _as_str_or_none(raw.get(key))
        if value:
            return value

    tool_input = raw.get("tool_input")
    if isinstance(tool_input, Mapping):
        for key in ("file_path", "path", "filepath"):
            value = _as_str_or_none(tool_input.get(key))
            if value:
                return value

    input_payload = raw.get("input_payload")
    if isinstance(input_payload, Mapping):
        for key in ("file_path", "path", "filepath"):
            value = _as_str_or_none(input_payload.get(key))
            if value:
                return value

    return None


def _file_changes_from_records(
    records: Sequence[RawRecord],
    *,
    max_items: int = DEFAULT_MAX_FILE_CHANGES,
) -> tuple[HandoffFileChange, ...]:
    """Build compact file-change records from raw session records."""

    seen: set[str] = set()
    changes: list[HandoffFileChange] = []

    for record in records:
        path = _extract_file_path(record)
        if path is None:
            continue

        normalised = path.replace("\\", "/").strip()
        if not normalised or normalised in seen:
            continue

        seen.add(normalised)
        changes.append(
            HandoffFileChange(
                path=normalised,
                status=HandoffFileStatus.UNKNOWN,
                reason="seen in recent stop-hook session records",
                important=False,
            )
        )

        if len(changes) >= max_items:
            break

    return tuple(changes)


def _handoff_basename(*, session_id: str | None, generated_at: str) -> str:
    """Return stable artifact basename."""

    timestamp = generated_at.replace(":", "").replace("+", "Z").replace(".", "-")
    return f"{_safe_slug(session_id)}-{timestamp}"


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically enough for local hook usage."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _merge_generated_context(
    hook_payload: Mapping[str, str],
    *,
    markdown_path: Path | None,
) -> dict[str, str]:
    """Merge runtime hook payload with generated handoff path context."""

    payload = dict(hook_payload)

    if markdown_path is None:
        return payload

    generated_note = (
        f"Pilot generated a handoff markdown file for this degraded session: {markdown_path}"
    )

    existing = payload.get("additionalContext")
    if existing:
        payload["additionalContext"] = f"{existing}\n\n{generated_note}"
    else:
        payload["additionalContext"] = generated_note

    return payload


def build_stop_handoff_schema(
    *,
    session_id: str | None,
    task: str | None,
    records: Sequence[RawRecord],
    runtime: PolicyRuntimeResult,
    generated_at: str,
) -> HandoffSchema:
    """Build a HandoffSchema for a stop-hook generated handoff."""

    blocker_extraction = extract_handoff_blockers(records)
    file_changes = _file_changes_from_records(records)

    task_text = task or "Continue Pilot session after stop-hook handoff"
    progress_text = (
        "Stop hook evaluated the session and selected "
        f"`{runtime.policy_decision.action.value}` with health "
        f"{runtime.health.health_score:.2f}. "
        f"Observed {len(records)} recent record(s), "
        f"{len(blocker_extraction.blockers)} blocker(s), and "
        f"{len(blocker_extraction.do_not_redo)} do-not-redo item(s)."
    )

    notes = (
        runtime.health.explanation,
        runtime.transition.explanation,
        runtime.policy_decision.explanation,
        blocker_extraction.explanation,
    )

    return HandoffSchema(
        session_id=session_id,
        generated_at=generated_at,
        task=task_text,
        progress=progress_text,
        files_modified=file_changes,
        blockers=blocker_extraction.blockers,
        next_step="Start a fresh session, load this handoff, and continue from the next concrete step.",
        do_not_redo=blocker_extraction.do_not_redo,
        notes=tuple(note for note in notes if note.strip()),
    )


def write_stop_handoff_artifacts(
    *,
    handoff: HandoffSchema,
    markdown: str,
    handoff_dir: str | Path,
) -> tuple[Path, Path]:
    """Write markdown and JSON artifacts and return their paths."""

    directory = Path(handoff_dir)
    basename = _handoff_basename(
        session_id=handoff.session_id,
        generated_at=handoff.generated_at or _utc_now(),
    )
    markdown_path = directory / f"{basename}.md"
    json_path = directory / f"{basename}.json"

    _atomic_write_text(markdown_path, markdown)
    _atomic_write_text(json_path, handoff_to_json(handoff))

    return markdown_path, json_path


def build_stop_handoff_result(
    signal_results: Mapping[Any, object] | Sequence[object],
    *,
    records: Sequence[RawRecord] = tuple(),
    session_id: str | None = None,
    task: str | None = None,
    current_state: SessionState = SessionState.HEALTHY,
    activation_modes: Mapping[object, object] | None = None,
    default_mode: ActivationMode | str = ActivationMode.ACTION,
    at_stop_hook: bool = True,
    turn_index: int | None = None,
    handoff_dir: str | Path | None = None,
    write_files: bool = False,
    generated_at: str | None = None,
) -> StopHandoffResult:
    """Run stop-hook policy and optionally generate handoff artifacts."""

    runtime = run_policy_runtime(
        signal_results,
        current_state=current_state,
        activation_modes=activation_modes,
        default_mode=default_mode,
        at_stop_hook=at_stop_hook,
        turn_index=turn_index,
    )

    if not runtime.should_prepare_handoff:
        return StopHandoffResult(
            runtime=runtime,
            handoff=None,
            markdown=None,
            markdown_path=None,
            json_path=None,
            hook_payload=dict(runtime.hook_payload),
            user_stderr=runtime.user_stderr,
            reason="policy_did_not_request_handoff",
        )

    if runtime.applied_policy.effective_mode is not ActivationMode.ACTION:
        return StopHandoffResult(
            runtime=runtime,
            handoff=None,
            markdown=None,
            markdown_path=None,
            json_path=None,
            hook_payload=dict(runtime.hook_payload),
            user_stderr=runtime.user_stderr,
            reason=f"handoff_suppressed_by_{runtime.applied_policy.effective_mode.value}_mode",
        )

    timestamp = generated_at or _utc_now()
    handoff = build_stop_handoff_schema(
        session_id=session_id,
        task=task,
        records=records,
        runtime=runtime,
        generated_at=timestamp,
    )
    markdown = render_handoff_markdown(
        handoff,
        options=HandoffMarkdownOptions(style=HandoffMarkdownStyle.FULL),
    )

    markdown_path: Path | None = None
    json_path: Path | None = None

    if write_files:
        target_dir = handoff_dir if handoff_dir is not None else DEFAULT_STOP_HANDOFF_DIR
        markdown_path, json_path = write_stop_handoff_artifacts(
            handoff=handoff,
            markdown=markdown,
            handoff_dir=target_dir,
        )

    hook_payload = _merge_generated_context(
        runtime.hook_payload,
        markdown_path=markdown_path,
    )

    return StopHandoffResult(
        runtime=runtime,
        handoff=handoff,
        markdown=markdown,
        markdown_path=markdown_path,
        json_path=json_path,
        hook_payload=hook_payload,
        user_stderr=runtime.user_stderr,
        reason="handoff_generated",
    )


def generate_stop_handoff_from_payload(
    payload: Mapping[str, object],
    *,
    handoff_dir: str | Path | None = None,
    write_files: bool | None = None,
) -> StopHandoffResult:
    """Build stop-hook handoff result from a JSON-like payload."""

    records = _extract_records(payload)
    signal_results = _extract_signal_results(payload)

    session_id = _as_str_or_none(payload.get("session_id"))
    task = _as_str_or_none(payload.get("task"))
    turn_index_raw = payload.get("turn_index")
    turn_index = int(turn_index_raw) if isinstance(turn_index_raw, int | float) else None

    current_state = _normalise_state(payload.get("current_state"))
    default_mode = payload.get("default_mode", ActivationMode.ACTION.value)

    payload_handoff_dir = _as_str_or_none(payload.get("handoff_dir"))
    resolved_handoff_dir = handoff_dir or payload_handoff_dir or os.getenv("PILOT_HANDOFF_DIR")
    resolved_write_files = (
        _as_bool(payload.get("write_files"), default=True) if write_files is None else write_files
    )

    return build_stop_handoff_result(
        signal_results,
        records=records,
        session_id=session_id,
        task=task,
        current_state=current_state,
        default_mode=default_mode if isinstance(default_mode, str) else ActivationMode.ACTION,
        at_stop_hook=True,
        turn_index=turn_index,
        handoff_dir=resolved_handoff_dir,
        write_files=resolved_write_files,
    )


def stop_handoff_summary(result: StopHandoffResult) -> dict[str, object]:
    """Return compact serialisable summary for tests, smoke scripts, and CLI."""

    markdown_summary: dict[str, object] | None = None
    if result.handoff is not None and result.markdown is not None:
        markdown_summary = handoff_markdown_summary(result.handoff, markdown=result.markdown)

    return {
        "reason": result.reason,
        "should_generate_handoff": result.should_generate_handoff,
        "effective_mode": result.runtime.applied_policy.effective_mode.value,
        "health_score": round(result.runtime.health.health_score, 4),
        "state": result.runtime.transition.next_state.value,
        "policy_action": result.runtime.policy_decision.action.value,
        "should_prepare_handoff": result.runtime.should_prepare_handoff,
        "markdown_path": str(result.markdown_path) if result.markdown_path else None,
        "json_path": str(result.json_path) if result.json_path else None,
        "has_stdout": result.should_emit_stdout,
        "has_stderr": result.should_emit_stderr,
        "hook_payload_keys": sorted(result.hook_payload),
        "markdown_summary": markdown_summary,
    }


def _safe_float_or_none(value: object) -> float | None:
    """Return value as float when possible."""

    if isinstance(value, bool):
        return None

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None

    return None


def _legacy_state_is_unhealthy(value: object) -> bool:
    """Return True when an older hook payload clearly says the session is unhealthy."""

    if isinstance(value, SessionState):
        return value in {
            SessionState.DEGRADING,
            SessionState.CRITICAL,
            SessionState.HANDOFF_PENDING,
        }

    if isinstance(value, str):
        normalised = value.strip().lower().replace("-", "_")
        return any(
            marker in normalised
            for marker in (
                "degrading",
                "degraded",
                "critical",
                "handoff_pending",
                "prepare_handoff",
            )
        )

    return False


def _legacy_object_indicates_unhealthy(value: object, *, key_hint: str = "") -> bool:
    """Recursively detect legacy unhealthy stop-hook payload shapes."""

    if _legacy_state_is_unhealthy(value):
        return True

    if isinstance(value, Mapping):
        for raw_key, nested_value in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")

            if key in {
                "state",
                "current_state",
                "session_state",
                "status",
                "severity",
            } and _legacy_state_is_unhealthy(nested_value):
                return True

            if key in {"critical", "degraded", "handoff_pending"} and nested_value is True:
                return True

            if (
                key
                in {
                    "should_prepare_handoff",
                    "prepare_handoff",
                    "handoff_requested",
                }
                and nested_value is True
            ):
                return True

            if key in {"health", "health_score", "session_health"} or (
                "health" in key and "score" in key
            ):
                health_score = _safe_float_or_none(nested_value)
                if health_score is not None and health_score < 0.40:
                    return True

            if key_hint in {"health", "session_health"} and key in {"score", "value"}:
                health_score = _safe_float_or_none(nested_value)
                if health_score is not None and health_score < 0.40:
                    return True

            if _legacy_object_indicates_unhealthy(nested_value, key_hint=key):
                return True

        return False

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_legacy_object_indicates_unhealthy(item, key_hint=key_hint) for item in value)

    return False


def _payload_indicates_legacy_unhealthy_session(payload: Mapping[str, object]) -> bool:
    """Detect older Day 21-style stop-hook payloads without signal_results."""

    return _legacy_object_indicates_unhealthy(payload)


def _legacy_stop_hook_payload() -> dict[str, str]:
    """Return minimal backward-compatible stop-hook stdout payload."""

    return {
        "additionalContext": (
            "Pilot detected a critical or degraded session at Stop. "
            "Pause, summarize progress, and prepare a handoff before continuing."
        )
    }


def _legacy_db_stop_hook_payload(payload: Mapping[str, object]) -> dict[str, str] | None:
    """Handle older Day 21 stop-hook payloads backed by the sessions table.

    Day 21 smoke does not send health/state in stdin. It stores the session
    state in SQLite and expects the Stop hook to:
    - read the session row
    - detect critical/degrading state
    - write a placeholder handoff file
    - update state to handoff_pending
    - emit additionalContext on stdout
    """

    session_id = _as_str_or_none(payload.get("session_id"))
    if session_id is None:
        return None

    try:
        import sqlite3

        from pilot_core.config import load_config
        from pilot_core.paths import resolve_runtime_paths

        runtime_paths = resolve_runtime_paths(load_config())
        db_path = runtime_paths.db_path

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT state FROM sessions WHERE id = ?;",
                (session_id,),
            ).fetchone()

            if row is None:
                return None

            state = str(row[0] or "").strip().lower().replace("-", "_")
            if state not in {"degrading", "critical", "handoff_pending"}:
                return None

            runtime_paths.handoff_dir.mkdir(parents=True, exist_ok=True)
            handoff_path = (
                runtime_paths.handoff_dir / f"{_safe_slug(session_id)}-legacy-stop-handoff.md"
            )

            if not handoff_path.exists():
                handoff_path.write_text(
                    "# Pilot Handoff\n\n"
                    "Pilot detected a critical or degraded session at Stop.\n\n"
                    "Next step: pause, summarize progress, and continue in a fresh session.\n",
                    encoding="utf-8",
                )

            conn.execute(
                """
                UPDATE sessions
                SET state = ?, handoff_summary_path = ?
                WHERE id = ?;
                """,
                ("handoff_pending", str(handoff_path), session_id),
            )
            conn.commit()

            return _legacy_stop_hook_payload()
        finally:
            conn.close()
    except Exception:
        return None


def _payload_has_signal_results(payload: Mapping[str, object]) -> bool:
    """Return True when payload uses the Day 47 signal-result shape."""

    for key in ("signal_results", "signals", "signal_outputs"):
        value = payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return True

    pilot_value = payload.get("pilot")
    if isinstance(pilot_value, Mapping):
        return _payload_has_signal_results(cast(Mapping[str, object], pilot_value))

    return False


def main() -> int:
    """Claude Code Stop hook entrypoint.

    This function is intentionally fail-silent: any internal Pilot error returns
    zero so the user's Claude Code session is not broken by Pilot.
    """
    try:
        raw_stdin = sys.stdin.read()
        if not raw_stdin.strip():
            return 0

        loaded = json.loads(raw_stdin)
        if not isinstance(loaded, Mapping):
            return 0

        payload = cast(Mapping[str, object], loaded)

        if not _payload_has_signal_results(payload):
            db_payload = _legacy_db_stop_hook_payload(payload)
            if db_payload is not None:
                print(json.dumps(db_payload, ensure_ascii=False, sort_keys=True))
                return 0

            if _payload_indicates_legacy_unhealthy_session(payload):
                print(
                    json.dumps(
                        _legacy_stop_hook_payload(),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return 0

        result = generate_stop_handoff_from_payload(payload)

        if result.should_emit_stderr:
            print(result.user_stderr, file=sys.stderr)

        if result.should_emit_stdout:
            print(json.dumps(result.hook_payload, ensure_ascii=False, sort_keys=True))

        return 0
    except Exception:
        return 0
