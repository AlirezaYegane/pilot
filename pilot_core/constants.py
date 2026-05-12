"""Project-wide constants and enum contracts for Pilot.

This module is intentionally small and dependency-free.

Rules:
- Enum values are stable because they are stored in config files, JSON payloads,
  SQLite rows, and future CLI output.
- Do not rename enum values casually.
- Add aliases/migrations first if a stored value ever needs to change.
"""

from __future__ import annotations

from enum import Enum
from typing import TypeVar


class _StrEnum(str, Enum):
    """Small Python 3.10-compatible string enum helper."""

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Return all raw string values for this enum."""

        return tuple(item.value for item in cls)

    @classmethod
    def has_value(cls, value: str) -> bool:
        """Return True if value is a valid enum value."""

        return value in cls.values()


class SessionState(_StrEnum):
    """Lifecycle state for a monitored Claude Code session."""

    HEALTHY = "healthy"
    WATCHING = "watching"
    DEGRADING = "degrading"
    CRITICAL = "critical"
    HANDOFF_PENDING = "handoff_pending"
    HANDED_OFF = "handed_off"


class SignalName(_StrEnum):
    """Canonical names for all degradation signals."""

    TOKEN_BURN = "token_burn"
    REPEATED_CALLS = "repeated_calls"
    ERROR_CASCADE = "error_cascade"
    BACKTRACKING = "backtracking"
    CONTEXT_SATURATION = "context_saturation"
    SELF_DOUBT = "self_doubt"
    RATE_LIMIT = "rate_limit"
    LOW_PRODUCTIVITY = "low_productivity"


class Severity(_StrEnum):
    """Severity levels used for signal explanations and user-facing warnings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ActivationMode(_StrEnum):
    """How strongly Pilot acts on a signal."""

    SHADOW = "shadow"
    WARN = "warn"
    ACTION = "action"


class HookEvent(_StrEnum):
    """Claude Code hook events used by Pilot."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    STOP = "Stop"
    SESSION_END = "SessionEnd"


class ConfigSource(_StrEnum):
    """Where a final config value came from."""

    DEFAULT = "default"
    FILE = "file"
    ENV = "env"


class ExitCode:
    """Process exit codes used by hooks and CLI commands."""

    OK = 0
    BLOCK = 2


class Defaults:
    """Stable default constants shared across modules."""

    PACKAGE_NAME = "pilot-cc"
    CLI_NAME = "pilot"

    DEFAULT_CONFIG_DIR_NAME = "pilot"
    DEFAULT_DATA_DIR_NAME = "data"
    DEFAULT_HANDOFF_DIR_NAME = "handoffs"
    DEFAULT_DEBUG_LOG_NAME = "debug.log"

    DEFAULT_CONTEXT_LIMIT = 200_000
    DEFAULT_SYSTEM_PROMPT_TOKEN_OFFSET = 20_000

    DEFAULT_WARNING_COOLDOWN_TURNS = 3
    DEFAULT_WARN_AFTER_TURN = 5

    HEALTH_HEALTHY_MIN = 0.80
    HEALTH_WATCHING_MIN = 0.60
    HEALTH_DEGRADING_MIN = 0.40
    STATE_HYSTERESIS = 0.05


ALL_SESSION_STATES: tuple[SessionState, ...] = tuple(SessionState)
ALL_SIGNAL_NAMES: tuple[SignalName, ...] = tuple(SignalName)
ALL_SEVERITIES: tuple[Severity, ...] = tuple(Severity)
ALL_ACTIVATION_MODES: tuple[ActivationMode, ...] = tuple(ActivationMode)
ALL_HOOK_EVENTS: tuple[HookEvent, ...] = tuple(HookEvent)


DEFAULT_SIGNAL_WEIGHTS: dict[SignalName, float] = {
    SignalName.TOKEN_BURN: 0.15,
    SignalName.REPEATED_CALLS: 0.20,
    SignalName.ERROR_CASCADE: 0.20,
    SignalName.BACKTRACKING: 0.10,
    SignalName.CONTEXT_SATURATION: 0.15,
    SignalName.SELF_DOUBT: 0.10,
    SignalName.RATE_LIMIT: 0.25,
    SignalName.LOW_PRODUCTIVITY: 0.10,
}


DEFAULT_SIGNAL_ACTIVATION_MODES: dict[SignalName, ActivationMode] = {
    SignalName.TOKEN_BURN: ActivationMode.SHADOW,
    SignalName.REPEATED_CALLS: ActivationMode.SHADOW,
    SignalName.ERROR_CASCADE: ActivationMode.SHADOW,
    SignalName.BACKTRACKING: ActivationMode.SHADOW,
    SignalName.CONTEXT_SATURATION: ActivationMode.SHADOW,
    SignalName.SELF_DOUBT: ActivationMode.SHADOW,
    SignalName.RATE_LIMIT: ActivationMode.SHADOW,
    SignalName.LOW_PRODUCTIVITY: ActivationMode.SHADOW,
}


EnumT = TypeVar("EnumT", bound=_StrEnum)


def parse_enum(enum_type: type[EnumT], value: str, *, field_name: str) -> EnumT:
    """Parse a string into a known enum value with a helpful error message."""

    try:
        return enum_type(value)
    except ValueError as exc:
        valid_values = ", ".join(enum_type.values())
        msg = f"Invalid {field_name}: {value!r}. Expected one of: {valid_values}"
        raise ValueError(msg) from exc


def parse_session_state(value: str) -> SessionState:
    """Parse a session state string."""

    return parse_enum(SessionState, value, field_name="session state")


def parse_signal_name(value: str) -> SignalName:
    """Parse a signal name string."""

    return parse_enum(SignalName, value, field_name="signal name")


def parse_severity(value: str) -> Severity:
    """Parse a severity string."""

    return parse_enum(Severity, value, field_name="severity")


def parse_activation_mode(value: str) -> ActivationMode:
    """Parse an activation mode string."""

    return parse_enum(ActivationMode, value, field_name="activation mode")


def is_terminal_session_state(state: SessionState) -> bool:
    """Return True if a session state means no more monitoring actions are expected."""

    return state is SessionState.HANDED_OFF


def should_prepare_handoff(state: SessionState) -> bool:
    """Return True if this state should prepare a handoff summary."""

    return state in {SessionState.CRITICAL, SessionState.HANDOFF_PENDING}


def signal_weight(signal_name: SignalName) -> float:
    """Return the configured default weight for a signal."""

    return DEFAULT_SIGNAL_WEIGHTS[signal_name]


def default_activation_mode(signal_name: SignalName) -> ActivationMode:
    """Return the default activation mode for a signal."""

    return DEFAULT_SIGNAL_ACTIVATION_MODES[signal_name]
