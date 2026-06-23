"""Session-start resume flow for Pilot handoffs.

Day 48 connects the handoff engine to the SessionStart hook.

Pipeline:
- find the latest previous handoff artifact
- prefer JSON handoff artifacts when available
- render/normalise handoff markdown
- expose the result as hook-safe additionalContext
- keep SessionStart fail-silent and backwards-compatible

This module is intentionally small and safe for hook usage. It performs only
local filesystem reads and optional lightweight session-row bootstrapping.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pilot_core.handoff import HandoffSchema, handoff_from_json, handoff_summary
from pilot_core.render.handoff_md import (
    HandoffMarkdownOptions,
    HandoffMarkdownStyle,
    render_handoff_markdown,
)
from pilot_core.stop_handoff import DEFAULT_STOP_HANDOFF_DIR

DEFAULT_MAX_RESUME_CONTEXT_CHARS = 6_000
RESUME_CONTEXT_TITLE = "Pilot resume context from previous handoff"


@dataclass(frozen=True)
class LoadedHandoffArtifact:
    """A loaded handoff artifact from disk."""

    path: Path
    markdown: str
    handoff: HandoffSchema | None
    source_format: str

    @property
    def is_json_backed(self) -> bool:
        """Return True when the artifact came from a JSON handoff."""

        return self.source_format == "json"


@dataclass(frozen=True)
class SessionResumeResult:
    """Hook-ready result for SessionStart resume flow."""

    session_id: str | None
    handoff_dir: Path
    artifact: LoadedHandoffArtifact | None
    hook_payload: dict[str, str]
    reason: str
    recorded_session: bool = False

    @property
    def should_emit_stdout(self) -> bool:
        """Return True when SessionStart should emit hook JSON."""

        return bool(self.hook_payload)

    @property
    def has_resume_context(self) -> bool:
        """Return True when a handoff context was loaded."""

        return self.artifact is not None and bool(self.hook_payload.get("additionalContext"))


def _as_str_or_none(value: object) -> str | None:
    """Return a stripped string or None."""

    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _as_mapping(value: object) -> Mapping[str, object] | None:
    """Return a string-key mapping when possible."""

    if isinstance(value, Mapping):
        return value

    return None


def _bounded_text(text: str, *, max_chars: int) -> str:
    """Return text bounded to a hook-safe size."""

    if max_chars <= 0:
        return ""

    if len(text) <= max_chars:
        return text

    suffix = "\n\n... [handoff truncated]"
    keep = max(0, max_chars - len(suffix))
    return f"{text[:keep]}{suffix}"


def _artifact_sort_key(path: Path) -> tuple[int, int, str]:
    """Return stable newest-first sort key components.

    JSON is preferred over markdown when timestamps tie, because JSON lets us
    validate and render the handoff with the current markdown renderer.
    """

    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0

    format_rank = 1 if path.suffix.lower() == ".json" else 0
    return (modified_ns, format_rank, path.name)


def handoff_artifact_candidates(handoff_dir: str | Path) -> tuple[Path, ...]:
    """Return handoff artifacts sorted newest-first."""

    directory = Path(handoff_dir)
    if not directory.exists() or not directory.is_dir():
        return tuple()

    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".json", ".md"}
    ]

    return tuple(sorted(candidates, key=_artifact_sort_key, reverse=True))


def load_handoff_artifact(path: str | Path) -> LoadedHandoffArtifact:
    """Load one handoff artifact from disk."""

    artifact_path = Path(path)
    text = artifact_path.read_text(encoding="utf-8")
    suffix = artifact_path.suffix.lower()

    if suffix == ".json":
        handoff = handoff_from_json(text)
        markdown = render_handoff_markdown(
            handoff,
            options=HandoffMarkdownOptions(style=HandoffMarkdownStyle.FULL),
        )
        return LoadedHandoffArtifact(
            path=artifact_path,
            markdown=markdown,
            handoff=handoff,
            source_format="json",
        )

    if suffix == ".md":
        return LoadedHandoffArtifact(
            path=artifact_path,
            markdown=text,
            handoff=None,
            source_format="markdown",
        )

    raise ValueError(f"Unsupported handoff artifact type: {artifact_path}")


def load_latest_handoff_artifact(handoff_dir: str | Path) -> LoadedHandoffArtifact | None:
    """Load the newest readable handoff artifact from a directory."""

    for candidate in handoff_artifact_candidates(handoff_dir):
        try:
            return load_handoff_artifact(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue

    return None


def render_resume_context(
    artifact: LoadedHandoffArtifact,
    *,
    max_chars: int = DEFAULT_MAX_RESUME_CONTEXT_CHARS,
) -> str:
    """Render a Claude-facing resume context from a loaded handoff."""

    header = (
        f"{RESUME_CONTEXT_TITLE}\n"
        f"Source: {artifact.path}\n"
        f"Format: {artifact.source_format}\n\n"
        "Use this handoff as the starting context for the new session. "
        "Continue from the Next Step, preserve decisions, and avoid repeating "
        "the Do Not Redo items.\n\n"
    )

    return _bounded_text(f"{header}{artifact.markdown.strip()}\n", max_chars=max_chars)


def _payload_handoff_dir(payload: Mapping[str, object]) -> object | None:
    """Extract handoff_dir from top-level or nested pilot payload."""

    if "handoff_dir" in payload:
        return payload.get("handoff_dir")

    pilot_value = _as_mapping(payload.get("pilot"))
    if pilot_value is not None:
        return pilot_value.get("handoff_dir")

    return None


def resolve_handoff_dir_from_payload(
    payload: Mapping[str, object],
    *,
    handoff_dir: str | Path | None = None,
) -> Path:
    """Resolve the handoff directory for a SessionStart payload."""

    raw_dir: object = handoff_dir

    if raw_dir is None:
        raw_dir = os.environ.get("PILOT_HANDOFF_DIR")

    if raw_dir is None:
        raw_dir = _payload_handoff_dir(payload)

    if raw_dir is None:
        raw_dir = DEFAULT_STOP_HANDOFF_DIR

    path = Path(str(raw_dir)).expanduser()

    if path.is_absolute():
        return path

    cwd = _as_str_or_none(payload.get("cwd"))
    base = Path(cwd).expanduser() if cwd is not None else Path.cwd()
    return base / path


def _record_session_start_legacy(payload: Mapping[str, object]) -> bool:
    """Create/update a lightweight sessions row for older hook smoke tests.

    This keeps Day 48 compatible with the earlier SessionStart contract:
    SessionStart should create/open a session record while also loading resume
    context when a handoff exists.
    """

    session_id = _as_str_or_none(payload.get("session_id"))
    if session_id is None:
        return False

    try:
        from pilot_core.config import load_config
        from pilot_core.paths import ensure_runtime_dirs, resolve_runtime_paths

        runtime_paths = ensure_runtime_dirs(resolve_runtime_paths(load_config()))
        conn = sqlite3.connect(runtime_paths.db_path)

        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    started_at INTEGER NOT NULL,
                    ended_at INTEGER,
                    cwd TEXT,
                    model TEXT,
                    parent_session_id TEXT,
                    total_input_tokens INTEGER DEFAULT 0,
                    total_output_tokens INTEGER DEFAULT 0,
                    estimated_cost_usd REAL DEFAULT 0,
                    state TEXT DEFAULT 'healthy',
                    handoff_summary_path TEXT
                )
                """
            )

            timestamp_value = payload.get("timestamp_ms", 0)
            started_at = timestamp_value if isinstance(timestamp_value, int) else 0

            conn.execute(
                """
                INSERT OR IGNORE INTO sessions (
                    id,
                    started_at,
                    cwd,
                    model,
                    parent_session_id,
                    state
                )
                VALUES (?, ?, ?, ?, ?, 'healthy')
                """,
                (
                    session_id,
                    started_at,
                    _as_str_or_none(payload.get("cwd")),
                    _as_str_or_none(payload.get("model")),
                    _as_str_or_none(payload.get("parent_session_id")),
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False


def build_session_resume_result(
    *,
    session_id: str | None = None,
    handoff_dir: str | Path,
    max_context_chars: int = DEFAULT_MAX_RESUME_CONTEXT_CHARS,
    recorded_session: bool = False,
) -> SessionResumeResult:
    """Build a hook-ready resume result from a handoff directory."""

    resolved_dir = Path(handoff_dir)
    artifact = load_latest_handoff_artifact(resolved_dir)

    if artifact is None:
        return SessionResumeResult(
            session_id=session_id,
            handoff_dir=resolved_dir,
            artifact=None,
            hook_payload={},
            reason="no_previous_handoff",
            recorded_session=recorded_session,
        )

    context = render_resume_context(artifact, max_chars=max_context_chars)

    if not context.strip():
        return SessionResumeResult(
            session_id=session_id,
            handoff_dir=resolved_dir,
            artifact=artifact,
            hook_payload={},
            reason="empty_resume_context",
            recorded_session=recorded_session,
        )

    return SessionResumeResult(
        session_id=session_id,
        handoff_dir=resolved_dir,
        artifact=artifact,
        hook_payload={"additionalContext": context},
        reason="loaded_previous_handoff",
        recorded_session=recorded_session,
    )


def generate_session_resume_from_payload(
    payload: Mapping[str, object],
    *,
    handoff_dir: str | Path | None = None,
    max_context_chars: int = DEFAULT_MAX_RESUME_CONTEXT_CHARS,
    record_session: bool = True,
) -> SessionResumeResult:
    """Generate SessionStart resume output from a hook payload."""

    session_id = _as_str_or_none(payload.get("session_id"))
    resolved_handoff_dir = resolve_handoff_dir_from_payload(payload, handoff_dir=handoff_dir)
    recorded_session = _record_session_start_legacy(payload) if record_session else False

    return build_session_resume_result(
        session_id=session_id,
        handoff_dir=resolved_handoff_dir,
        max_context_chars=max_context_chars,
        recorded_session=recorded_session,
    )


def session_resume_summary(result: SessionResumeResult) -> dict[str, object]:
    """Return a compact serialisable summary for smoke tests and future CLI."""

    artifact = result.artifact

    handoff_payload: dict[str, object] | None = None
    if artifact is not None and artifact.handoff is not None:
        handoff_payload = handoff_summary(artifact.handoff)

    context = result.hook_payload.get("additionalContext", "")

    return {
        "session_id": result.session_id,
        "handoff_dir": str(result.handoff_dir),
        "has_resume_context": result.has_resume_context,
        "should_emit_stdout": result.should_emit_stdout,
        "reason": result.reason,
        "recorded_session": result.recorded_session,
        "artifact_path": str(artifact.path) if artifact is not None else None,
        "artifact_format": artifact.source_format if artifact is not None else None,
        "context_char_count": len(context),
        "context_preview": context.splitlines()[:12],
        "handoff": handoff_payload,
    }


def main() -> int:
    """SessionStart hook entrypoint.

    The hook is fail-silent: any error returns 0 and emits nothing.
    """

    try:
        raw = sys.stdin.read().strip()
        payload: Mapping[str, object]

        if raw:
            parsed = json.loads(raw)
            payload = parsed if isinstance(parsed, Mapping) else {}
        else:
            payload = {}

        result = generate_session_resume_from_payload(payload)

        if result.hook_payload:
            print(json.dumps(result.hook_payload, ensure_ascii=False, sort_keys=True))

        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
