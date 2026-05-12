from __future__ import annotations

from collections.abc import Callable

import pytest

from pilot_core.constants import (
    ALL_ACTIVATION_MODES,
    ALL_HOOK_EVENTS,
    ALL_SESSION_STATES,
    ALL_SEVERITIES,
    ALL_SIGNAL_NAMES,
    DEFAULT_SIGNAL_ACTIVATION_MODES,
    DEFAULT_SIGNAL_WEIGHTS,
    ActivationMode,
    Defaults,
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


def test_session_state_values_are_stable() -> None:
    assert SessionState.values() == (
        "healthy",
        "watching",
        "degrading",
        "critical",
        "handoff_pending",
        "handed_off",
    )


def test_signal_name_values_are_stable() -> None:
    assert SignalName.values() == (
        "token_burn",
        "repeated_calls",
        "error_cascade",
        "backtracking",
        "context_saturation",
        "self_doubt",
        "rate_limit",
        "low_productivity",
    )


def test_severity_values_are_stable() -> None:
    assert Severity.values() == ("info", "warning", "error", "critical")


def test_activation_mode_values_are_stable() -> None:
    assert ActivationMode.values() == ("shadow", "warn", "action")


def test_hook_event_values_are_stable() -> None:
    assert HookEvent.values() == (
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "Stop",
        "SessionEnd",
    )


def test_all_constant_tuples_match_enums() -> None:
    assert tuple(SessionState) == ALL_SESSION_STATES
    assert tuple(SignalName) == ALL_SIGNAL_NAMES
    assert tuple(Severity) == ALL_SEVERITIES
    assert tuple(ActivationMode) == ALL_ACTIVATION_MODES
    assert tuple(HookEvent) == ALL_HOOK_EVENTS


def test_signal_weights_cover_all_signals() -> None:
    assert set(DEFAULT_SIGNAL_WEIGHTS) == set(SignalName)
    assert all(0.0 < weight <= 1.0 for weight in DEFAULT_SIGNAL_WEIGHTS.values())


def test_signal_activation_modes_cover_all_signals() -> None:
    assert set(DEFAULT_SIGNAL_ACTIVATION_MODES) == set(SignalName)
    assert all(mode is ActivationMode.SHADOW for mode in DEFAULT_SIGNAL_ACTIVATION_MODES.values())


def test_parse_helpers_accept_valid_values() -> None:
    assert parse_session_state("healthy") is SessionState.HEALTHY
    assert parse_signal_name("token_burn") is SignalName.TOKEN_BURN
    assert parse_severity("warning") is Severity.WARNING
    assert parse_activation_mode("warn") is ActivationMode.WARN


def test_parse_helpers_raise_helpful_errors() -> None:
    cases: tuple[tuple[Callable[[str], object], str], ...] = (
        (parse_session_state, "done"),
        (parse_signal_name, "token_burn_rate"),
        (parse_severity, "fatal"),
        (parse_activation_mode, "notify"),
    )

    for parser, bad_value in cases:
        with pytest.raises(ValueError, match="Expected one of"):
            parser(bad_value)


def test_session_state_policy_helpers() -> None:
    assert is_terminal_session_state(SessionState.HANDED_OFF)
    assert not is_terminal_session_state(SessionState.HEALTHY)

    assert should_prepare_handoff(SessionState.CRITICAL)
    assert should_prepare_handoff(SessionState.HANDOFF_PENDING)
    assert not should_prepare_handoff(SessionState.WATCHING)


def test_signal_helper_functions() -> None:
    assert signal_weight(SignalName.RATE_LIMIT) == 0.25
    assert default_activation_mode(SignalName.RATE_LIMIT) is ActivationMode.SHADOW


def test_defaults_are_sane() -> None:
    assert Defaults.PACKAGE_NAME == "pilot-cc"
    assert Defaults.CLI_NAME == "pilot"
    assert Defaults.DEFAULT_CONTEXT_LIMIT > 0
    assert Defaults.DEFAULT_SYSTEM_PROMPT_TOKEN_OFFSET > 0
    assert Defaults.DEFAULT_WARNING_COOLDOWN_TURNS >= 1
    assert Defaults.DEFAULT_WARN_AFTER_TURN >= 1
    assert (
        0.0
        < Defaults.HEALTH_DEGRADING_MIN
        < Defaults.HEALTH_WATCHING_MIN
        < Defaults.HEALTH_HEALTHY_MIN
        <= 1.0
    )
    assert Defaults.STATE_HYSTERESIS > 0
