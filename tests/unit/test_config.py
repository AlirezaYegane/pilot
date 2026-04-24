from __future__ import annotations

from pathlib import Path

import pytest

from pilot_core.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    ConfigError,
    default_config,
    get_config_path,
    load_config,
)


def test_default_config_is_local_first() -> None:
    config = default_config()

    assert config.quiet is False
    assert config.storage.data_dir == DEFAULT_DATA_DIR
    assert config.storage.handoff_dir == DEFAULT_DATA_DIR / "handoffs"
    assert config.signals.token_burn_ratio == 2.0
    assert config.signals.repeated_call_count == 3
    assert config.signals.error_cascade_rate == 0.4
    assert config.signals.default_activation_mode == "shadow"
    assert config.context.system_prompt_token_offset == 20_000


def test_get_config_path_uses_default_when_env_is_missing() -> None:
    assert get_config_path(env={}) == DEFAULT_CONFIG_PATH


def test_get_config_path_can_be_overridden_by_env(tmp_path: Path) -> None:
    custom_path = tmp_path / "pilot.yaml"

    assert get_config_path(env={"PILOT_CONFIG": str(custom_path)}) == custom_path


def test_load_config_reads_yaml_file_and_keeps_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"

    config_file.write_text(
        f"""
quiet: true
storage:
  data_dir: "{data_dir.as_posix()}"
signals:
  token_burn_ratio: 3.5
  default_activation_mode: warn
budget:
  plan: max20
context:
  default_context_limit: 1000000
""",
        encoding="utf-8",
    )

    config = load_config(config_path=config_file, env={})

    assert config.quiet is True
    assert config.storage.data_dir == data_dir
    assert config.storage.handoff_dir == data_dir / "handoffs"
    assert config.signals.token_burn_ratio == 3.5
    assert config.signals.repeated_call_count == 3
    assert config.signals.default_activation_mode == "warn"
    assert config.budget.plan == "max20"
    assert config.context.default_context_limit == 1_000_000


def test_env_overrides_file_values(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    file_data_dir = tmp_path / "file-data"
    env_data_dir = tmp_path / "env-data"

    config_file.write_text(
        f"""
quiet: false
storage:
  data_dir: "{file_data_dir.as_posix()}"
signals:
  token_burn_ratio: 2.5
  default_activation_mode: shadow
budget:
  weekly_token_cap: 100
""",
        encoding="utf-8",
    )

    config = load_config(
        config_path=config_file,
        env={
            "PILOT_QUIET": "true",
            "PILOT_DATA_DIR": str(env_data_dir),
            "PILOT_TOKEN_BURN_RATIO": "4.2",
            "PILOT_DEFAULT_ACTIVATION_MODE": "action",
            "PILOT_WEEKLY_TOKEN_CAP": "1234",
        },
    )

    assert config.quiet is True
    assert config.storage.data_dir == env_data_dir
    assert config.signals.token_burn_ratio == 4.2
    assert config.signals.default_activation_mode == "action"
    assert config.budget.weekly_token_cap == 1234


def test_empty_config_file_is_allowed(tmp_path: Path) -> None:
    config_file = tmp_path / "empty.yaml"
    config_file.write_text("", encoding="utf-8")

    config = load_config(config_path=config_file, env={})

    assert config == default_config()


def test_invalid_config_shape_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "invalid.yaml"
    config_file.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path=config_file, env={})


def test_unknown_config_key_raises_config_error(tmp_path: Path) -> None:
    config_file = tmp_path / "unknown.yaml"
    config_file.write_text("unknown_key: true\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path=config_file, env={})
