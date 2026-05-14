"""Fail-silent runtime helpers for Pilot hooks.

Pilot must never break the user's Claude Code session.

Hook code should use these helpers around non-critical work. If something goes
wrong, Pilot logs the error locally and returns a safe fallback.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

from pilot_core.paths import resolve_runtime_paths

P = ParamSpec("P")
T = TypeVar("T")


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for debug log lines."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_string(value: object, *, limit: int = 4_000) -> str:
    """Convert an arbitrary object to a bounded string for logs."""

    try:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = repr(value)

    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated]"


def write_debug_log(message: str, *, debug_log_path: str | Path | None = None) -> None:
    """Append a message to Pilot's debug log.

    This function is intentionally fail-silent. Logging must never become the
    reason a hook fails.
    """

    try:
        if debug_log_path is None:
            path = resolve_runtime_paths().debug_log_path
        else:
            path = Path(debug_log_path)

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(f"{utc_timestamp()} {message}\n")
    except Exception:
        return


def log_exception(
    exc: BaseException,
    *,
    context: str = "",
    debug_log_path: str | Path | None = None,
    include_traceback: bool = False,
) -> None:
    """Log an exception without raising another exception."""

    context_part = f" context={context}" if context else ""
    message = f"[pilot-error]{context_part} {type(exc).__name__}: {safe_string(exc)}"

    if include_traceback:
        message = f"{message}\n{traceback.format_exc()}"

    write_debug_log(message, debug_log_path=debug_log_path)


def run_safely(
    operation: Callable[[], T],
    *,
    default: T,
    context: str = "",
    debug_log_path: str | Path | None = None,
) -> T:
    """Run a zero-argument operation and return default if it fails."""

    try:
        return operation()
    except Exception as exc:
        log_exception(exc, context=context, debug_log_path=debug_log_path)
        return default


def fail_silent(
    default: T,
    *,
    context: str = "",
    debug_log_path: str | Path | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator that turns unexpected exceptions into a safe fallback value."""

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                effective_context = context or func.__name__
                log_exception(exc, context=effective_context, debug_log_path=debug_log_path)
                return default

        return wrapper

    return decorator
