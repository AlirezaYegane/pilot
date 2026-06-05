"""Signal registry and activation policy for Pilot.

Day 33 goal:
- register all 8 degradation signals in one stable registry
- support dynamic enable/disable per signal
- support shadow/warn/action activation mode per signal

This module does not compute the final session health score yet. That belongs
to the upcoming decision/state layer. The registry only evaluates signals and
normalises their policy outcome.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pilot_core.constants import (
    ActivationMode,
    Severity,
    SignalName,
    default_activation_mode,
    parse_activation_mode,
    parse_severity,
    parse_signal_name,
)

SignalEvaluator = Callable[[Sequence[Any]], object]


@dataclass(frozen=True)
class SignalRegistryConfig:
    """Dynamic registry configuration.

    enabled_signals:
        If None, every registered signal is eligible.
        If set, only listed signals are eligible.

    disabled_signals:
        Always excluded, even if present in enabled_signals.

    activation_overrides:
        Per-signal override for shadow/warn/action.

    default_activation:
        Optional fallback activation mode for signals without an explicit
        override. If None, Pilot's project defaults are used.
    """

    enabled_signals: frozenset[SignalName] | None = None
    disabled_signals: frozenset[SignalName] = field(default_factory=frozenset)
    activation_overrides: Mapping[SignalName, ActivationMode] = field(default_factory=dict)
    default_activation: ActivationMode | None = None

    def is_enabled(self, signal_name: SignalName) -> bool:
        """Return True if a signal should be evaluated."""

        if self.enabled_signals is not None and signal_name not in self.enabled_signals:
            return False

        return signal_name not in self.disabled_signals

    def activation_for(self, signal_name: SignalName) -> ActivationMode:
        """Return the activation mode for a signal."""

        if signal_name in self.activation_overrides:
            return self.activation_overrides[signal_name]

        if self.default_activation is not None:
            return self.default_activation

        return default_activation_mode(signal_name)


@dataclass(frozen=True)
class SignalRegistryEntry:
    """One registered signal evaluator."""

    signal_name: SignalName
    evaluator: SignalEvaluator
    activation_mode: ActivationMode
    enabled: bool = True


@dataclass(frozen=True)
class SignalRegistryEvaluation:
    """Normalised evaluation returned by the registry."""

    signal_name: SignalName
    score: float
    confidence: float
    severity: Severity
    activation_mode: ActivationMode
    enabled: bool
    fired: bool
    should_warn: bool
    should_action: bool
    explanation: str
    source_result: object | None = None

    @property
    def shadowed(self) -> bool:
        """Return True when a fired signal is intentionally shadow-only."""

        return self.enabled and self.fired and self.activation_mode is ActivationMode.SHADOW


def clamp_score(value: float) -> float:
    """Clamp a score into the 0..1 range."""

    return max(0.0, min(1.0, value))


def _safe_float(value: object, *, default: float = 0.0) -> float:
    """Convert unknown result values to float safely."""

    if isinstance(value, bool):
        return float(value)

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default

    return default


def _coerce_signal_name(value: object, *, default: SignalName) -> SignalName:
    """Coerce a raw signal name into SignalName."""

    if isinstance(value, SignalName):
        return value

    if isinstance(value, str):
        return parse_signal_name(value)

    return default


def _coerce_severity(value: object) -> Severity:
    """Coerce a raw severity into Severity."""

    if isinstance(value, Severity):
        return value

    if isinstance(value, str):
        return parse_severity(value)

    return Severity.INFO


def _coerce_activation_mode(value: object) -> ActivationMode:
    """Coerce a raw activation mode into ActivationMode."""

    if isinstance(value, ActivationMode):
        return value

    if isinstance(value, str):
        return parse_activation_mode(value)

    raise ValueError(f"Invalid activation mode: {value!r}")


def _as_sequence(value: object) -> tuple[Any, ...]:
    """Normalise config sequence values."""

    if value is None:
        return tuple()

    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())

    if isinstance(value, Sequence):
        return tuple(value)

    return (value,)


def _parse_signal_set(value: object) -> frozenset[SignalName] | None:
    """Parse a config value into a signal-name set."""

    if value is None:
        return None

    names = [
        _coerce_signal_name(item, default=SignalName.ERROR_CASCADE) for item in _as_sequence(value)
    ]
    return frozenset(names)


def _parse_activation_overrides(value: object) -> dict[SignalName, ActivationMode]:
    """Parse per-signal activation overrides from config-like mappings."""

    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise ValueError("activation overrides must be a mapping")

    parsed: dict[SignalName, ActivationMode] = {}

    for raw_signal_name, raw_mode in value.items():
        signal_name = _coerce_signal_name(raw_signal_name, default=SignalName.ERROR_CASCADE)
        parsed[signal_name] = _coerce_activation_mode(raw_mode)

    return parsed


def signal_registry_config_from_config(config: object) -> SignalRegistryConfig:
    """Build SignalRegistryConfig from the project's flexible config object.

    This intentionally accepts optional attributes so we can add config fields
    later without breaking older config versions.
    """

    signals_config = getattr(config, "signals", None)

    if signals_config is None:
        return SignalRegistryConfig()

    enabled_signals = _parse_signal_set(getattr(signals_config, "enabled_signals", None))
    disabled_signals = _parse_signal_set(getattr(signals_config, "disabled_signals", None))

    activation_overrides_raw = getattr(signals_config, "activation_modes", None)
    if activation_overrides_raw is None:
        activation_overrides_raw = getattr(signals_config, "signal_activation_modes", None)

    activation_overrides = _parse_activation_overrides(activation_overrides_raw)

    default_activation_raw = getattr(signals_config, "default_activation_mode", None)
    default_activation = (
        _coerce_activation_mode(default_activation_raw)
        if default_activation_raw is not None
        else None
    )

    return SignalRegistryConfig(
        enabled_signals=enabled_signals,
        disabled_signals=disabled_signals or frozenset(),
        activation_overrides=activation_overrides,
        default_activation=default_activation,
    )


def _normalise_evaluation(
    *,
    entry: SignalRegistryEntry,
    result: object,
) -> SignalRegistryEvaluation:
    """Convert a signal-specific result into a registry-level result."""

    signal_name = _coerce_signal_name(
        getattr(result, "signal_name", entry.signal_name),
        default=entry.signal_name,
    )
    score = clamp_score(_safe_float(getattr(result, "score", 0.0)))
    confidence = clamp_score(_safe_float(getattr(result, "confidence", 0.0)))
    severity = _coerce_severity(getattr(result, "severity", Severity.INFO))
    explanation = str(getattr(result, "explanation", "")).strip()

    fired_attr = getattr(result, "fired", None)
    fired = bool(fired_attr) if fired_attr is not None else score > 0.0

    should_warn = fired and entry.activation_mode in {
        ActivationMode.WARN,
        ActivationMode.ACTION,
    }
    should_action = fired and entry.activation_mode is ActivationMode.ACTION

    return SignalRegistryEvaluation(
        signal_name=signal_name,
        score=score,
        confidence=confidence,
        severity=severity,
        activation_mode=entry.activation_mode,
        enabled=entry.enabled,
        fired=fired,
        should_warn=should_warn,
        should_action=should_action,
        explanation=explanation,
        source_result=result,
    )


def _disabled_evaluation(entry: SignalRegistryEntry) -> SignalRegistryEvaluation:
    """Return a cheap disabled result without calling the signal evaluator."""

    return SignalRegistryEvaluation(
        signal_name=entry.signal_name,
        score=0.0,
        confidence=1.0,
        severity=Severity.INFO,
        activation_mode=entry.activation_mode,
        enabled=False,
        fired=False,
        should_warn=False,
        should_action=False,
        explanation=f"{entry.signal_name.value} is disabled by signal registry policy.",
        source_result=None,
    )


class SignalRegistry:
    """Registry for enabled/disabled signal evaluators."""

    def __init__(self, entries: Sequence[SignalRegistryEntry]) -> None:
        if not entries:
            raise ValueError("SignalRegistry requires at least one entry")

        self._entries = {entry.signal_name: entry for entry in entries}

        if len(self._entries) != len(entries):
            raise ValueError("Duplicate signal registry entries are not allowed")

    @classmethod
    def from_evaluators(
        cls,
        evaluators: Mapping[SignalName, SignalEvaluator],
        *,
        registry_config: SignalRegistryConfig | None = None,
    ) -> SignalRegistry:
        """Create a registry from evaluator functions and policy config."""

        config = registry_config or SignalRegistryConfig()
        entries = [
            SignalRegistryEntry(
                signal_name=signal_name,
                evaluator=evaluator,
                activation_mode=config.activation_for(signal_name),
                enabled=config.is_enabled(signal_name),
            )
            for signal_name, evaluator in evaluators.items()
        ]
        return cls(entries)

    def names(self) -> tuple[SignalName, ...]:
        """Return all registered signal names."""

        return tuple(self._entries)

    def enabled_names(self) -> tuple[SignalName, ...]:
        """Return enabled signal names."""

        return tuple(name for name, entry in self._entries.items() if entry.enabled)

    def entry(self, signal_name: SignalName | str) -> SignalRegistryEntry:
        """Return a registry entry by signal name."""

        parsed_name = (
            signal_name if isinstance(signal_name, SignalName) else parse_signal_name(signal_name)
        )

        try:
            return self._entries[parsed_name]
        except KeyError as exc:
            raise KeyError(f"Signal is not registered: {parsed_name.value}") from exc

    def with_signal_enabled(
        self, signal_name: SignalName | str, *, enabled: bool
    ) -> SignalRegistry:
        """Return a new registry with one signal enabled/disabled."""

        parsed_name = (
            signal_name if isinstance(signal_name, SignalName) else parse_signal_name(signal_name)
        )

        entries = [
            SignalRegistryEntry(
                signal_name=entry.signal_name,
                evaluator=entry.evaluator,
                activation_mode=entry.activation_mode,
                enabled=enabled if entry.signal_name is parsed_name else entry.enabled,
            )
            for entry in self._entries.values()
        ]

        return SignalRegistry(entries)

    def with_activation_mode(
        self,
        signal_name: SignalName | str,
        activation_mode: ActivationMode | str,
    ) -> SignalRegistry:
        """Return a new registry with one signal activation mode changed."""

        parsed_name = (
            signal_name if isinstance(signal_name, SignalName) else parse_signal_name(signal_name)
        )
        parsed_mode = _coerce_activation_mode(activation_mode)

        entries = [
            SignalRegistryEntry(
                signal_name=entry.signal_name,
                evaluator=entry.evaluator,
                activation_mode=parsed_mode
                if entry.signal_name is parsed_name
                else entry.activation_mode,
                enabled=entry.enabled,
            )
            for entry in self._entries.values()
        ]

        return SignalRegistry(entries)

    def evaluate_signal(
        self,
        signal_name: SignalName | str,
        records: Sequence[Any],
    ) -> SignalRegistryEvaluation:
        """Evaluate one registered signal."""

        entry = self.entry(signal_name)

        if not entry.enabled:
            return _disabled_evaluation(entry)

        result = entry.evaluator(records)
        return _normalise_evaluation(entry=entry, result=result)

    def evaluate_many(
        self,
        records_by_signal: Mapping[SignalName | str, Sequence[Any]],
    ) -> tuple[SignalRegistryEvaluation, ...]:
        """Evaluate every registered signal using per-signal record sets.

        Missing record sets are passed as an empty tuple.
        """

        evaluations: list[SignalRegistryEvaluation] = []

        normalised_records: dict[SignalName, Sequence[Any]] = {}
        for raw_name, records in records_by_signal.items():
            signal_name = (
                raw_name if isinstance(raw_name, SignalName) else parse_signal_name(raw_name)
            )
            normalised_records[signal_name] = records

        for signal_name in self._entries:
            records = normalised_records.get(signal_name, tuple())
            evaluations.append(self.evaluate_signal(signal_name, records))

        return tuple(evaluations)


def _default_signal_evaluators() -> dict[SignalName, SignalEvaluator]:
    """Import and return the default 8 signal evaluators lazily."""

    from pilot_core.signals.backtracking import evaluate_backtracking
    from pilot_core.signals.context_saturation import evaluate_context_saturation
    from pilot_core.signals.error_cascade import evaluate_error_cascade
    from pilot_core.signals.low_productivity import evaluate_low_productivity
    from pilot_core.signals.rate_limit import evaluate_rate_limit
    from pilot_core.signals.repeated_calls import evaluate_repeated_calls
    from pilot_core.signals.self_doubt import evaluate_self_doubt
    from pilot_core.signals.token_burn import evaluate_token_burn

    def token_burn(records: Sequence[Any]) -> object:
        return evaluate_token_burn(records)

    def repeated_calls(records: Sequence[Any]) -> object:
        return evaluate_repeated_calls(tuple(records))

    def error_cascade(records: Sequence[Any]) -> object:
        return evaluate_error_cascade(tuple(records))

    def backtracking(records: Sequence[Any]) -> object:
        return evaluate_backtracking(records)

    def context_saturation(records: Sequence[Any]) -> object:
        return evaluate_context_saturation(records)

    def self_doubt(records: Sequence[Any]) -> object:
        return evaluate_self_doubt(records)

    def rate_limit(records: Sequence[Any]) -> object:
        return evaluate_rate_limit(records)

    def low_productivity(records: Sequence[Any]) -> object:
        return evaluate_low_productivity(records)

    return {
        SignalName.TOKEN_BURN: token_burn,
        SignalName.REPEATED_CALLS: repeated_calls,
        SignalName.ERROR_CASCADE: error_cascade,
        SignalName.BACKTRACKING: backtracking,
        SignalName.CONTEXT_SATURATION: context_saturation,
        SignalName.SELF_DOUBT: self_doubt,
        SignalName.RATE_LIMIT: rate_limit,
        SignalName.LOW_PRODUCTIVITY: low_productivity,
    }


def build_default_signal_registry(
    *,
    registry_config: SignalRegistryConfig | None = None,
) -> SignalRegistry:
    """Build the default registry containing all 8 Pilot signals."""

    return SignalRegistry.from_evaluators(
        _default_signal_evaluators(),
        registry_config=registry_config,
    )
