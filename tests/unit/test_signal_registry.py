from __future__ import annotations

from collections.abc import Callable, Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from pilot_core.constants import ActivationMode, Severity, SignalName
from pilot_core.signals.registry import (
    SignalRegistry,
    SignalRegistryConfig,
    SignalRegistryEvaluation,
    build_default_signal_registry,
    signal_registry_config_from_config,
)


def _fake_result(
    *,
    signal_name: SignalName = SignalName.ERROR_CASCADE,
    score: float = 0.8,
    confidence: float = 1.0,
    severity: Severity = Severity.WARNING,
    fired: bool = True,
    explanation: str = "fake signal fired",
) -> object:
    return SimpleNamespace(
        signal_name=signal_name,
        score=score,
        confidence=confidence,
        severity=severity,
        fired=fired,
        explanation=explanation,
    )


def _fake_evaluator(result: object) -> Callable[[Sequence[Any]], object]:
    def evaluate(_records: Sequence[Any]) -> object:
        return result

    return evaluate


def test_default_signal_registry_contains_all_8_signals() -> None:
    registry = build_default_signal_registry()

    assert set(registry.names()) == set(SignalName)
    assert set(registry.enabled_names()) == set(SignalName)


def test_registry_supports_disabled_signals_without_calling_evaluator() -> None:
    called = False

    def evaluator(_records: object) -> object:
        nonlocal called
        called = True
        return _fake_result()

    registry = SignalRegistry.from_evaluators(
        {SignalName.ERROR_CASCADE: evaluator},
        registry_config=SignalRegistryConfig(
            disabled_signals=frozenset({SignalName.ERROR_CASCADE}),
        ),
    )

    result = registry.evaluate_signal(SignalName.ERROR_CASCADE, [])

    assert called is False
    assert result.enabled is False
    assert result.fired is False
    assert result.should_warn is False
    assert result.should_action is False
    assert "disabled" in result.explanation


def test_activation_modes_control_policy_outcome() -> None:
    cases: list[tuple[ActivationMode, bool, bool, bool]] = [
        (ActivationMode.SHADOW, False, False, True),
        (ActivationMode.WARN, True, False, False),
        (ActivationMode.ACTION, True, True, False),
    ]

    for activation_mode, should_warn, should_action, shadowed in cases:
        registry = SignalRegistry.from_evaluators(
            {
                SignalName.ERROR_CASCADE: _fake_evaluator(
                    _fake_result(signal_name=SignalName.ERROR_CASCADE),
                )
            },
            registry_config=SignalRegistryConfig(
                activation_overrides={SignalName.ERROR_CASCADE: activation_mode},
            ),
        )

        result = registry.evaluate_signal(SignalName.ERROR_CASCADE, [])

        assert result.enabled is True
        assert result.fired is True
        assert result.activation_mode is activation_mode
        assert result.should_warn is should_warn
        assert result.should_action is should_action
        assert result.shadowed is shadowed


def test_registry_can_be_changed_immutably() -> None:
    registry = SignalRegistry.from_evaluators(
        {
            SignalName.ERROR_CASCADE: _fake_evaluator(
                _fake_result(signal_name=SignalName.ERROR_CASCADE),
            )
        },
    )

    disabled = registry.with_signal_enabled(SignalName.ERROR_CASCADE, enabled=False)
    action = registry.with_activation_mode(SignalName.ERROR_CASCADE, ActivationMode.ACTION)

    assert registry.entry(SignalName.ERROR_CASCADE).enabled is True
    assert disabled.entry(SignalName.ERROR_CASCADE).enabled is False
    assert action.entry(SignalName.ERROR_CASCADE).activation_mode is ActivationMode.ACTION


def test_evaluate_many_accepts_string_signal_keys() -> None:
    registry = SignalRegistry.from_evaluators(
        {
            SignalName.ERROR_CASCADE: _fake_evaluator(
                _fake_result(signal_name=SignalName.ERROR_CASCADE),
            )
        },
        registry_config=SignalRegistryConfig(
            activation_overrides={SignalName.ERROR_CASCADE: ActivationMode.WARN},
        ),
    )

    results = registry.evaluate_many({"error_cascade": [{"success": False}]})

    assert len(results) == 1
    assert isinstance(results[0], SignalRegistryEvaluation)
    assert results[0].signal_name is SignalName.ERROR_CASCADE
    assert results[0].should_warn is True


def test_signal_registry_config_from_flexible_config_object() -> None:
    config = SimpleNamespace(
        signals=SimpleNamespace(
            enabled_signals=["error_cascade", "rate_limit"],
            disabled_signals=["self_doubt"],
            activation_modes={
                "error_cascade": "warn",
                "rate_limit": "action",
            },
            default_activation_mode="shadow",
        )
    )

    registry_config = signal_registry_config_from_config(config)

    assert registry_config.enabled_signals == frozenset(
        {SignalName.ERROR_CASCADE, SignalName.RATE_LIMIT}
    )
    assert registry_config.disabled_signals == frozenset({SignalName.SELF_DOUBT})
    assert registry_config.activation_for(SignalName.ERROR_CASCADE) is ActivationMode.WARN
    assert registry_config.activation_for(SignalName.RATE_LIMIT) is ActivationMode.ACTION
    assert registry_config.activation_for(SignalName.TOKEN_BURN) is ActivationMode.SHADOW


def test_unknown_signal_name_is_rejected() -> None:
    registry = SignalRegistry.from_evaluators(
        {
            SignalName.ERROR_CASCADE: _fake_evaluator(
                _fake_result(signal_name=SignalName.ERROR_CASCADE),
            )
        },
    )

    with pytest.raises(ValueError, match="Invalid signal name"):
        registry.evaluate_signal("not_a_signal", [])
