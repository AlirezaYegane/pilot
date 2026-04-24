"""Configuration loading for Pilot.

Precedence:
1. Built-in defaults
2. YAML config file
3. Environment variables
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_PILOT_HOME = Path.home() / ".claude" / "plugins" / "pilot"
DEFAULT_CONFIG_PATH = DEFAULT_PILOT_HOME / "config.yaml"
DEFAULT_DATA_DIR = DEFAULT_PILOT_HOME / "data"
DEFAULT_DEBUG_LOG_PATH = DEFAULT_PILOT_HOME / "debug.log"


class ConfigError(RuntimeError):
    """Raised when Pilot configuration cannot be loaded or validated."""


class StorageConfig(BaseModel):
    """Local storage paths used by Pilot."""

    model_config = ConfigDict(extra="forbid")

    data_dir: Path = Field(default=DEFAULT_DATA_DIR)
    debug_log_path: Path = Field(default=DEFAULT_DEBUG_LOG_PATH)
    handoff_dir_name: str = Field(default="handoffs", min_length=1)

    @property
    def handoff_dir(self) -> Path:
        """Directory where handoff markdown files are stored."""
        return self.data_dir / self.handoff_dir_name


class SignalConfig(BaseModel):
    """Thresholds and behaviour for degradation signals."""

    model_config = ConfigDict(extra="forbid")

    token_burn_ratio: float = Field(default=2.0, gt=0)
    repeated_call_count: int = Field(default=3, ge=1)
    error_cascade_rate: float = Field(default=0.4, ge=0, le=1)
    backtracking_count: int = Field(default=2, ge=1)
    context_saturation_ratio: float = Field(default=0.80, gt=0, le=1)
    self_doubt_marker_count: int = Field(default=3, ge=1)
    rate_limit_eta_minutes: int = Field(default=20, ge=1)
    low_productivity_ratio: float = Field(default=0.5, gt=0)

    default_activation_mode: str = Field(default="shadow")
    warn_after_turn: int = Field(default=5, ge=0)
    warning_cooldown_turns: int = Field(default=3, ge=0)


class BudgetConfig(BaseModel):
    """Budget and usage estimation config."""

    model_config = ConfigDict(extra="forbid")

    plan: str = Field(default="max5", min_length=1)
    weekly_token_cap: int = Field(default=250_000_000, ge=1)
    warning_usage_ratio: float = Field(default=0.80, gt=0, le=1)


class ContextConfig(BaseModel):
    """Context-window estimation settings."""

    model_config = ConfigDict(extra="forbid")

    default_context_limit: int = Field(default=200_000, ge=1)
    system_prompt_token_offset: int = Field(default=20_000, ge=0)


class PilotConfig(BaseModel):
    """Top-level Pilot configuration."""

    model_config = ConfigDict(extra="forbid")

    quiet: bool = False
    storage: StorageConfig = Field(default_factory=StorageConfig)
    signals: SignalConfig = Field(default_factory=SignalConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)


def default_config() -> PilotConfig:
    """Return Pilot's built-in default configuration."""
    return PilotConfig()


def get_config_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the config path from env or the default local-first path."""
    env_source = env if env is not None else os.environ
    configured_path = env_source.get("PILOT_CONFIG")

    if configured_path:
        return Path(configured_path).expanduser()

    return DEFAULT_CONFIG_PATH


def load_config(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> PilotConfig:
    """Load config using defaults, optional YAML file, then env overrides."""
    env_source = env if env is not None else os.environ
    resolved_path = config_path if config_path is not None else get_config_path(env_source)

    data: dict[str, Any] = {}

    file_data = _load_yaml_config(resolved_path)
    data = _deep_merge(data, file_data)

    env_data = _env_overrides(env_source)
    data = _deep_merge(data, env_data)

    try:
        return PilotConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid Pilot config: {exc}") from exc


def _load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Could not read config file: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in config file: {path}") from exc

    if raw is None:
        return {}

    if not isinstance(raw, Mapping):
        raise ConfigError("Pilot config file must contain a YAML mapping/object.")

    raw_mapping = cast(Mapping[object, Any], raw)
    return {str(key): value for key, value in raw_mapping.items()}


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)

    for key, value in override.items():
        existing = merged.get(key)

        if isinstance(existing, dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value

    return merged


def _env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}

    _set_from_env(overrides, env, "PILOT_QUIET", None, "quiet", _parse_bool)

    _set_from_env(overrides, env, "PILOT_DATA_DIR", "storage", "data_dir", str)
    _set_from_env(overrides, env, "PILOT_DEBUG_LOG", "storage", "debug_log_path", str)
    _set_from_env(overrides, env, "PILOT_HANDOFF_DIR_NAME", "storage", "handoff_dir_name", str)

    _set_from_env(
        overrides,
        env,
        "PILOT_TOKEN_BURN_RATIO",
        "signals",
        "token_burn_ratio",
        float,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_REPEATED_CALL_COUNT",
        "signals",
        "repeated_call_count",
        int,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_ERROR_CASCADE_RATE",
        "signals",
        "error_cascade_rate",
        float,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_BACKTRACKING_COUNT",
        "signals",
        "backtracking_count",
        int,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_CONTEXT_SATURATION_RATIO",
        "signals",
        "context_saturation_ratio",
        float,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_SELF_DOUBT_MARKER_COUNT",
        "signals",
        "self_doubt_marker_count",
        int,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_RATE_LIMIT_ETA_MINUTES",
        "signals",
        "rate_limit_eta_minutes",
        int,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_LOW_PRODUCTIVITY_RATIO",
        "signals",
        "low_productivity_ratio",
        float,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_DEFAULT_ACTIVATION_MODE",
        "signals",
        "default_activation_mode",
        str,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_WARN_AFTER_TURN",
        "signals",
        "warn_after_turn",
        int,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_WARNING_COOLDOWN_TURNS",
        "signals",
        "warning_cooldown_turns",
        int,
    )

    _set_from_env(overrides, env, "PILOT_PLAN", "budget", "plan", str)
    _set_from_env(overrides, env, "PILOT_WEEKLY_TOKEN_CAP", "budget", "weekly_token_cap", int)
    _set_from_env(
        overrides,
        env,
        "PILOT_WARNING_USAGE_RATIO",
        "budget",
        "warning_usage_ratio",
        float,
    )

    _set_from_env(
        overrides,
        env,
        "PILOT_CONTEXT_LIMIT",
        "context",
        "default_context_limit",
        int,
    )
    _set_from_env(
        overrides,
        env,
        "PILOT_SYSTEM_PROMPT_TOKEN_OFFSET",
        "context",
        "system_prompt_token_offset",
        int,
    )

    return overrides


def _set_from_env(
    target: dict[str, Any],
    env: Mapping[str, str],
    env_name: str,
    section: str | None,
    key: str,
    parser: Callable[[str], Any],
) -> None:
    raw_value = env.get(env_name)

    if raw_value is None:
        return

    value = parser(raw_value)

    _set_override(target, section, key, value)


def _set_override(
    target: dict[str, Any],
    section: str | None,
    key: str,
    value: Any,
) -> None:
    if section is None:
        target[key] = value
        return

    current_value = target.get(section)

    if isinstance(current_value, dict):
        current_value[key] = value
        return

    new_section_map: dict[str, Any] = {key: value}
    target[section] = new_section_map


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()

    if normalized in {"1", "true", "yes", "y", "on"}:
        return True

    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    raise ValueError(f"Invalid boolean value: {value!r}")
