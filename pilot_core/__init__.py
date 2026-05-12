"""Pilot core package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from pilot_core.constants import (
    ALL_ACTIVATION_MODES,
    ALL_HOOK_EVENTS,
    ALL_SESSION_STATES,
    ALL_SEVERITIES,
    ALL_SIGNAL_NAMES,
    DEFAULT_SIGNAL_ACTIVATION_MODES,
    DEFAULT_SIGNAL_WEIGHTS,
    ActivationMode,
    ConfigSource,
    Defaults,
    ExitCode,
    HookEvent,
    SessionState,
    Severity,
    SignalName,
    default_activation_mode,
    is_terminal_session_state,
    parse_activation_mode,
    parse_session_state,
    parse_severity,
    parse_signal_name,
    should_prepare_handoff,
    signal_weight,
)
from pilot_core.paths import (
    RuntimePaths,
    default_data_dir,
    default_debug_log_path,
    ensure_runtime_dirs,
    expand_path,
    resolve_runtime_paths,
    runtime_path_summary,
)
from pilot_core.safety import (
    fail_silent,
    log_exception,
    run_safely,
    safe_string,
    utc_timestamp,
    write_debug_log,
)

try:
    __version__ = version("pilot-cc")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "ALL_ACTIVATION_MODES",
    "ALL_HOOK_EVENTS",
    "ALL_SESSION_STATES",
    "ALL_SEVERITIES",
    "ALL_SIGNAL_NAMES",
    "DEFAULT_SIGNAL_ACTIVATION_MODES",
    "DEFAULT_SIGNAL_WEIGHTS",
    "ActivationMode",
    "ConfigSource",
    "Defaults",
    "ExitCode",
    "HookEvent",
    "RuntimePaths",
    "SessionState",
    "Severity",
    "SignalName",
    "__version__",
    "default_activation_mode",
    "default_data_dir",
    "default_debug_log_path",
    "ensure_runtime_dirs",
    "expand_path",
    "fail_silent",
    "is_terminal_session_state",
    "log_exception",
    "parse_activation_mode",
    "parse_session_state",
    "parse_severity",
    "parse_signal_name",
    "resolve_runtime_paths",
    "run_safely",
    "runtime_path_summary",
    "safe_string",
    "should_prepare_handoff",
    "signal_weight",
    "utc_timestamp",
    "write_debug_log",
]
