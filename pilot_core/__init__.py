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
    "SessionState",
    "Severity",
    "SignalName",
    "__version__",
    "default_activation_mode",
    "is_terminal_session_state",
    "parse_activation_mode",
    "parse_session_state",
    "parse_severity",
    "parse_signal_name",
    "should_prepare_handoff",
    "signal_weight",
]
