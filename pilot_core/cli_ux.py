"""Terminal UX helpers for Pilot CLI.

Day 56 adds a small shared presentation layer for CLI commands.

Goals:
- use Rich when available
- keep a deterministic plain-text fallback
- standardise errors, success messages, health bars, and tables
- avoid importing Rich directly so mypy stays clean and CLI still works without it
"""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, TextIO

from pilot_core.constants import SessionState

DEFAULT_HEALTH_BAR_WIDTH = 20
DEFAULT_TABLE_VALUE_WIDTH = 44


class CliMessageKind(str, Enum):
    """Common CLI message kinds."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class CliError:
    """Structured CLI error that can be rendered consistently."""

    title: str
    message: str
    hint: str = ""
    command: str = ""
    exit_code: int = 1


@dataclass(frozen=True)
class CliStatusRow:
    """One key/value row for terminal rendering."""

    key: str
    value: str
    style: str = ""


@dataclass(frozen=True)
class CliHealthView:
    """Compact health summary for status-like commands."""

    state: SessionState
    health_score: float
    fired_count: int = 0
    observed_signal_count: int = 0
    title: str = "Pilot status"


_RICH_MARKUP_PATTERN = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9 _#=.-]*\]")


def _optional_import(module_name: str) -> Any | None:
    """Import an optional module without turning it into a hard dependency."""

    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


def rich_is_available() -> bool:
    """Return True when Rich can be imported."""

    return _optional_import("rich.console") is not None


def install_cli_traceback(*, show_locals: bool = False) -> bool:
    """Install Rich traceback support when Rich is available.

    The function is intentionally fail-silent because CLI polish should never
    break the actual command being executed.
    """

    rich_traceback = _optional_import("rich.traceback")
    if rich_traceback is None:
        return False

    install = getattr(rich_traceback, "install", None)
    if not callable(install):
        return False

    try:
        install(show_locals=show_locals)
    except Exception:
        return False

    return True


def clamp_health_score(value: float) -> float:
    """Clamp health score into the 0..1 range."""

    return max(0.0, min(1.0, value))


def health_percent(value: float) -> int:
    """Return health score as a rounded integer percent."""

    return round(clamp_health_score(value) * 100)


def health_bar(value: float, *, width: int = DEFAULT_HEALTH_BAR_WIDTH) -> str:
    """Return a deterministic unicode health bar."""

    if width < 4:
        raise ValueError("width must be at least 4")

    score = clamp_health_score(value)
    filled = round(score * width)
    empty = width - filled
    return "█" * filled + "░" * empty


def state_style(state: SessionState) -> str:
    """Return Rich style name for a session state."""

    if state is SessionState.HEALTHY:
        return "green"
    if state is SessionState.WATCHING:
        return "cyan"
    if state is SessionState.DEGRADING:
        return "yellow"
    if state is SessionState.CRITICAL:
        return "red"
    if state is SessionState.HANDOFF_PENDING:
        return "magenta"
    if state is SessionState.HANDED_OFF:
        return "blue"

    return "white"


def message_style(kind: CliMessageKind) -> str:
    """Return Rich style for a message kind."""

    if kind is CliMessageKind.SUCCESS:
        return "green"
    if kind is CliMessageKind.WARNING:
        return "yellow"
    if kind is CliMessageKind.ERROR:
        return "red"
    return "cyan"


def strip_rich_markup(value: str) -> str:
    """Remove the small subset of Rich markup produced by this module."""

    return _RICH_MARKUP_PATTERN.sub("", value)


def _state_value(state: SessionState, *, use_markup: bool) -> str:
    """Render state as plain text or Rich markup."""

    if not use_markup:
        return state.value

    return f"[{state_style(state)}]{state.value}[/{state_style(state)}]"


def format_cli_error(error: CliError, *, use_markup: bool = False) -> str:
    """Render a structured CLI error."""

    if use_markup:
        lines = [f"[bold red]✖ {error.title}[/bold red]", error.message]
    else:
        lines = [f"✖ {error.title}", error.message]

    if error.hint:
        hint_label = "[bold]Hint[/bold]" if use_markup else "Hint"
        lines.append(f"{hint_label}: {error.hint}")

    if error.command:
        command_label = "[bold]Command[/bold]" if use_markup else "Command"
        lines.append(f"{command_label}: {error.command}")

    lines.append(f"Exit code: {max(0, error.exit_code)}")
    return "\n".join(lines)


def format_message(
    message: str,
    *,
    kind: CliMessageKind = CliMessageKind.INFO,
    use_markup: bool = False,
) -> str:
    """Render a one-line CLI message."""

    icon = {
        CliMessageKind.INFO: "i",
        CliMessageKind.SUCCESS: "✓",
        CliMessageKind.WARNING: "!",
        CliMessageKind.ERROR: "✖",
    }[kind]

    if not use_markup:
        return f"{icon} {message}"

    style = message_style(kind)
    return f"[{style}]{icon} {message}[/{style}]"


def render_health_view(view: CliHealthView, *, use_markup: bool = False) -> str:
    """Render a compact health view for CLI status output."""

    score = clamp_health_score(view.health_score)
    percent = health_percent(score)
    bar = health_bar(score)

    rows = [
        CliStatusRow(
            "State", _state_value(view.state, use_markup=use_markup), state_style(view.state)
        ),
        CliStatusRow("Health", f"{bar} {percent}%"),
        CliStatusRow(
            "Signals", f"{view.fired_count} fired / {view.observed_signal_count} observed"
        ),
    ]

    return render_key_value_table(rows, title=view.title, use_markup=use_markup)


def render_key_value_table(
    rows: Sequence[CliStatusRow],
    *,
    title: str = "Pilot",
    use_markup: bool = False,
    value_width: int = DEFAULT_TABLE_VALUE_WIDTH,
) -> str:
    """Render a deterministic key/value table that works without Rich."""

    cleaned_title = title.strip() or "Pilot"
    lines = [cleaned_title, "-" * len(strip_rich_markup(cleaned_title))]

    for row in rows:
        key = row.key.strip()
        value = row.value.strip()

        if not use_markup:
            value = strip_rich_markup(value)

        if len(strip_rich_markup(value)) > value_width:
            value = strip_rich_markup(value)[: value_width - 15].rstrip() + "... [truncated]"

        lines.append(f"{key:<18} {value}")

    return "\n".join(lines)


def render_mapping_table(
    values: Mapping[str, object],
    *,
    title: str = "Pilot",
    use_markup: bool = False,
) -> str:
    """Render a mapping as a stable key/value table."""

    rows = [
        CliStatusRow(key=str(key), value=str(value))
        for key, value in sorted(values.items(), key=lambda item: item[0])
    ]
    return render_key_value_table(rows, title=title, use_markup=use_markup)


def _make_rich_console(file: TextIO | None, *, stderr: bool) -> Any | None:
    """Create a Rich console when Rich is available."""

    console_module = _optional_import("rich.console")
    if console_module is None:
        return None

    console_cls = getattr(console_module, "Console", None)
    if not callable(console_cls):
        return None

    try:
        return console_cls(file=file, stderr=stderr, soft_wrap=True)
    except Exception:
        return None


def _write_plain(text: str, *, file: TextIO | None = None) -> None:
    """Write plain text to a stream."""

    target = file if file is not None else sys.stdout
    target.write(text)
    if not text.endswith("\n"):
        target.write("\n")


def write_text(
    text: str,
    *,
    file: TextIO | None = None,
    stderr: bool = False,
    use_rich: bool = True,
) -> str:
    """Write text to terminal using Rich when available, and return emitted text."""

    if use_rich:
        console = _make_rich_console(file, stderr=stderr)
        if console is not None:
            try:
                console.print(text, markup=True)
                return text
            except Exception:
                pass

    plain = strip_rich_markup(text)
    _write_plain(plain, file=file if file is not None else (sys.stderr if stderr else sys.stdout))
    return plain


def write_error(
    error: CliError,
    *,
    file: TextIO | None = None,
    use_rich: bool = True,
) -> str:
    """Write a structured CLI error to stderr-style output."""

    rendered = format_cli_error(error, use_markup=use_rich and rich_is_available())
    return write_text(rendered, file=file, stderr=True, use_rich=use_rich)


def write_health_view(
    view: CliHealthView,
    *,
    file: TextIO | None = None,
    use_rich: bool = True,
) -> str:
    """Write a health view to terminal and return emitted text."""

    rendered = render_health_view(view, use_markup=use_rich and rich_is_available())
    return write_text(rendered, file=file, use_rich=use_rich)


def success(message: str, *, use_markup: bool = False) -> str:
    """Return a standard success message."""

    return format_message(message, kind=CliMessageKind.SUCCESS, use_markup=use_markup)


def warning(message: str, *, use_markup: bool = False) -> str:
    """Return a standard warning message."""

    return format_message(message, kind=CliMessageKind.WARNING, use_markup=use_markup)


def error(message: str, *, use_markup: bool = False) -> str:
    """Return a standard error message."""

    return format_message(message, kind=CliMessageKind.ERROR, use_markup=use_markup)


__all__ = [
    "CliError",
    "CliHealthView",
    "CliMessageKind",
    "CliStatusRow",
    "clamp_health_score",
    "error",
    "format_cli_error",
    "format_message",
    "health_bar",
    "health_percent",
    "install_cli_traceback",
    "render_health_view",
    "render_key_value_table",
    "render_mapping_table",
    "rich_is_available",
    "state_style",
    "strip_rich_markup",
    "success",
    "warning",
    "write_error",
    "write_health_view",
    "write_text",
]
