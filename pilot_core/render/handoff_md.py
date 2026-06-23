"""Markdown renderer for Pilot handoff summaries.

Day 46 converts the stable HandoffSchema into concise, deterministic markdown.

This module intentionally does not:
- read from SQLite
- call hooks
- decide whether a handoff should happen
- generate summaries from raw events

It only renders an existing HandoffSchema into markdown that can be stored,
shown by CLI, or injected into a future session-start resume flow.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from pilot_core.handoff import (
    HandoffBlocker,
    HandoffDecision,
    HandoffDoNotRedo,
    HandoffFileChange,
    HandoffSchema,
)

T = TypeVar("T")

DEFAULT_MAX_SECTION_ITEMS = 8
DEFAULT_MAX_TEXT_CHARS = 700


class HandoffMarkdownStyle(str, Enum):
    """Supported markdown output styles."""

    COMPACT = "compact"
    FULL = "full"


@dataclass(frozen=True)
class HandoffMarkdownOptions:
    """Options controlling markdown rendering."""

    style: HandoffMarkdownStyle = HandoffMarkdownStyle.COMPACT
    include_metadata: bool = True
    include_empty_sections: bool = False
    max_section_items: int = DEFAULT_MAX_SECTION_ITEMS
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS


def _normalise_style(value: HandoffMarkdownStyle | str) -> HandoffMarkdownStyle:
    """Normalise style from enum or string."""

    if isinstance(value, HandoffMarkdownStyle):
        return value

    try:
        return HandoffMarkdownStyle(value)
    except ValueError as exc:
        raise ValueError(f"Unknown handoff markdown style: {value!r}") from exc


def _normalise_options(
    options: HandoffMarkdownOptions | None = None,
) -> HandoffMarkdownOptions:
    """Return validated markdown options."""

    if options is None:
        return HandoffMarkdownOptions()

    style = _normalise_style(options.style)

    if options.max_section_items < 1:
        raise ValueError("max_section_items must be greater than or equal to 1")

    if options.max_text_chars < 80:
        raise ValueError("max_text_chars must be greater than or equal to 80")

    return HandoffMarkdownOptions(
        style=style,
        include_metadata=options.include_metadata,
        include_empty_sections=options.include_empty_sections,
        max_section_items=options.max_section_items,
        max_text_chars=options.max_text_chars,
    )


def _clean_text(value: object) -> str:
    """Return a compact one-line markdown-safe text value."""

    text = str(value).strip()
    if not text:
        return ""

    return " ".join(text.split())


def _bounded_text(value: object, *, max_chars: int) -> str:
    """Return compact text bounded to max_chars."""

    text = _clean_text(value)
    if len(text) <= max_chars:
        return text

    suffix = "... [truncated]"
    keep = max(0, max_chars - len(suffix))
    return f"{text[:keep]}{suffix}"


def _inline_code(value: object) -> str:
    """Return a safe inline-code markdown value."""

    text = _clean_text(value).replace("`", "'")
    return f"`{text}`"


def _append_section(lines: list[str], title: str, body_lines: Sequence[str]) -> None:
    """Append a markdown section when it has content."""

    if not body_lines:
        return

    if lines and lines[-1] != "":
        lines.append("")

    lines.append(f"## {title}")
    lines.extend(body_lines)


def _limited_items(items: Sequence[T], *, max_items: int) -> tuple[tuple[T, ...], int]:
    """Return visible items plus hidden count."""

    visible = tuple(items[:max_items])
    hidden_count = max(0, len(items) - len(visible))
    return visible, hidden_count


def _render_metadata(handoff: HandoffSchema) -> list[str]:
    """Render compact metadata lines."""

    lines: list[str] = [
        f"- Schema: `{handoff.schema_version}`",
        f"- Generated: `{handoff.generated_at}`",
    ]

    if handoff.session_id:
        lines.insert(0, f"- Session: `{handoff.session_id}`")

    return lines


def _render_decisions(
    decisions: Sequence[HandoffDecision],
    *,
    options: HandoffMarkdownOptions,
) -> list[str]:
    """Render decision records."""

    visible, hidden_count = _limited_items(decisions, max_items=options.max_section_items)
    lines: list[str] = []

    for decision in visible:
        title = _bounded_text(decision.title, max_chars=options.max_text_chars)
        rationale = _bounded_text(decision.rationale, max_chars=options.max_text_chars)

        if rationale:
            lines.append(f"- **{title}** — {rationale}")
        else:
            lines.append(f"- **{title}**")

        if options.style is HandoffMarkdownStyle.FULL and decision.alternatives_rejected:
            rejected = ", ".join(
                _bounded_text(item, max_chars=160)
                for item in decision.alternatives_rejected
                if _clean_text(item)
            )
            if rejected:
                lines.append(f"  - Rejected: {rejected}")

    if hidden_count:
        lines.append(f"- _{hidden_count} more decision(s) omitted._")

    return lines


def _render_files(
    files: Sequence[HandoffFileChange],
    *,
    options: HandoffMarkdownOptions,
) -> list[str]:
    """Render modified files."""

    visible, hidden_count = _limited_items(files, max_items=options.max_section_items)
    lines: list[str] = []

    for file_change in visible:
        status = file_change.status.value
        path = _inline_code(file_change.path)
        reason = _bounded_text(file_change.reason, max_chars=options.max_text_chars)
        importance = " important" if file_change.important else ""

        if reason:
            lines.append(f"- **{status}**{importance}: {path} — {reason}")
        else:
            lines.append(f"- **{status}**{importance}: {path}")

    if hidden_count:
        lines.append(f"- _{hidden_count} more file change(s) omitted._")

    return lines


def _render_blockers(
    blockers: Sequence[HandoffBlocker],
    *,
    options: HandoffMarkdownOptions,
) -> list[str]:
    """Render blockers."""

    visible, hidden_count = _limited_items(blockers, max_items=options.max_section_items)
    lines: list[str] = []

    for blocker in visible:
        severity = blocker.severity.value
        description = _bounded_text(blocker.description, max_chars=options.max_text_chars)
        evidence = _bounded_text(blocker.evidence, max_chars=options.max_text_chars)

        if evidence and options.style is HandoffMarkdownStyle.FULL:
            lines.append(f"- **{severity}**: {description}")
            lines.append(f"  - Evidence: {evidence}")
        elif evidence:
            lines.append(f"- **{severity}**: {description} — {evidence}")
        else:
            lines.append(f"- **{severity}**: {description}")

    if hidden_count:
        lines.append(f"- _{hidden_count} more blocker(s) omitted._")

    return lines


def _render_do_not_redo(
    items: Sequence[HandoffDoNotRedo],
    *,
    options: HandoffMarkdownOptions,
) -> list[str]:
    """Render do-not-redo records."""

    visible, hidden_count = _limited_items(items, max_items=options.max_section_items)
    lines: list[str] = []

    for item in visible:
        item_text = _bounded_text(item.item, max_chars=options.max_text_chars)
        reason = _bounded_text(item.reason, max_chars=options.max_text_chars)

        if reason:
            lines.append(f"- **{item_text}** — {reason}")
        else:
            lines.append(f"- **{item_text}**")

    if hidden_count:
        lines.append(f"- _{hidden_count} more do-not-redo item(s) omitted._")

    return lines


def _render_notes(
    notes: Sequence[str],
    *,
    options: HandoffMarkdownOptions,
) -> list[str]:
    """Render optional notes."""

    visible, hidden_count = _limited_items(notes, max_items=options.max_section_items)
    lines = [
        f"- {_bounded_text(note, max_chars=options.max_text_chars)}"
        for note in visible
        if _clean_text(note)
    ]

    if hidden_count:
        lines.append(f"- _{hidden_count} more note(s) omitted._")

    return lines


def _maybe_empty(lines: list[str], title: str, options: HandoffMarkdownOptions) -> None:
    """Append an explicit empty section when requested."""

    if options.include_empty_sections:
        _append_section(lines, title, ["_None._"])


def render_handoff_markdown(
    handoff: HandoffSchema,
    *,
    options: HandoffMarkdownOptions | None = None,
) -> str:
    """Render a HandoffSchema into concise markdown."""

    resolved = _normalise_options(options)

    lines: list[str] = ["# Pilot Handoff"]

    if resolved.include_metadata:
        _append_section(lines, "Metadata", _render_metadata(handoff))

    task = _bounded_text(handoff.task, max_chars=resolved.max_text_chars)
    progress = _bounded_text(handoff.progress, max_chars=resolved.max_text_chars)
    next_step = _bounded_text(handoff.next_step, max_chars=resolved.max_text_chars)

    _append_section(lines, "Task", [task] if task else ["_Missing task._"])
    _append_section(lines, "Progress", [progress] if progress else ["_Missing progress._"])

    validation_errors = handoff.validation_errors()
    if validation_errors:
        _append_section(
            lines,
            "Validation Warnings",
            [f"- {error}" for error in validation_errors],
        )

    decisions = _render_decisions(handoff.decisions, options=resolved)
    if decisions:
        _append_section(lines, "Decisions", decisions)
    else:
        _maybe_empty(lines, "Decisions", resolved)

    files = _render_files(handoff.files_modified, options=resolved)
    if files:
        _append_section(lines, "Files Modified", files)
    else:
        _maybe_empty(lines, "Files Modified", resolved)

    blockers = _render_blockers(handoff.blockers, options=resolved)
    if blockers:
        _append_section(lines, "Blockers", blockers)
    else:
        _maybe_empty(lines, "Blockers", resolved)

    _append_section(lines, "Next Step", [next_step] if next_step else ["_Missing next step._"])

    do_not_redo = _render_do_not_redo(handoff.do_not_redo, options=resolved)
    if do_not_redo:
        _append_section(lines, "Do Not Redo", do_not_redo)
    else:
        _maybe_empty(lines, "Do Not Redo", resolved)

    notes = _render_notes(handoff.notes, options=resolved)
    if notes:
        _append_section(lines, "Notes", notes)
    else:
        _maybe_empty(lines, "Notes", resolved)

    return "\n".join(lines).strip() + "\n"


def handoff_markdown_summary(
    handoff: HandoffSchema,
    *,
    markdown: str | None = None,
) -> dict[str, object]:
    """Return a compact serialisable markdown summary."""

    rendered = markdown if markdown is not None else render_handoff_markdown(handoff)

    return {
        "line_count": len(rendered.splitlines()),
        "char_count": len(rendered),
        "has_metadata": "## Metadata" in rendered,
        "has_decisions": "## Decisions" in rendered,
        "has_files_modified": "## Files Modified" in rendered,
        "has_blockers": "## Blockers" in rendered,
        "has_do_not_redo": "## Do Not Redo" in rendered,
        "is_valid_handoff": handoff.is_valid(),
        "validation_error_count": len(handoff.validation_errors()),
    }
