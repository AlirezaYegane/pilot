"""Smoke test for Day 33 signal registry."""

from __future__ import annotations

import json
from types import SimpleNamespace

from pilot_core.constants import ActivationMode, Severity, SignalName
from pilot_core.signals.registry import (
    SignalRegistry,
    SignalRegistryConfig,
    build_default_signal_registry,
)


def fake_error_cascade(_records: object) -> object:
    """Return a deterministic fired signal for policy smoke testing."""

    return SimpleNamespace(
        signal_name=SignalName.ERROR_CASCADE,
        score=0.9,
        confidence=1.0,
        severity=Severity.CRITICAL,
        fired=True,
        explanation="smoke error cascade fired",
    )


def main() -> None:
    default_registry = build_default_signal_registry()

    policy_registry = SignalRegistry.from_evaluators(
        {SignalName.ERROR_CASCADE: fake_error_cascade},
        registry_config=SignalRegistryConfig(
            activation_overrides={SignalName.ERROR_CASCADE: ActivationMode.ACTION},
        ),
    )

    result = policy_registry.evaluate_signal(SignalName.ERROR_CASCADE, [{"success": False}])

    payload = {
        "status": "passed",
        "registered_signal_count": len(default_registry.names()),
        "registered_signals": [signal.value for signal in default_registry.names()],
        "policy_signal": result.signal_name.value,
        "activation_mode": result.activation_mode.value,
        "fired": result.fired,
        "should_warn": result.should_warn,
        "should_action": result.should_action,
    }

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
