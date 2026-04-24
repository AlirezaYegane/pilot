from __future__ import annotations

from typer.testing import CliRunner

from pilot_core.cli import app
from pilot_core.config import DEFAULT_CONFIG_PATH

runner = CliRunner()


def test_cli_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "pilot-cc 0.1.0" in result.output


def test_cli_doctor_command() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Pilot doctor OK" in result.output


def test_cli_config_path_command() -> None:
    result = runner.invoke(app, ["config-path"])

    assert result.exit_code == 0
    assert str(DEFAULT_CONFIG_PATH) in result.output


def test_cli_show_config_command() -> None:
    result = runner.invoke(app, ["show-config"])

    assert result.exit_code == 0
    assert "storage" in result.output
    assert "signals" in result.output
    assert "budget" in result.output
    assert "context" in result.output
