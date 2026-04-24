from __future__ import annotations

from typer.testing import CliRunner

from pilot_core.cli import app

runner = CliRunner()


def test_cli_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "pilot-cc 0.1.0" in result.output


def test_cli_doctor_command() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Pilot doctor OK" in result.output
