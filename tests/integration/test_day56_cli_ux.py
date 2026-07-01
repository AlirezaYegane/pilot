from __future__ import annotations

from io import StringIO

from pilot_core.cli_ux import (
    CliError,
    CliHealthView,
    CliStatusRow,
    format_cli_error,
    render_health_view,
    render_key_value_table,
    write_error,
    write_health_view,
)
from pilot_core.constants import SessionState


def test_day56_cli_error_output_is_terminal_safe() -> None:
    rendered = format_cli_error(
        CliError(
            title="Broken install",
            message="Pilot hooks are not registered.",
            hint="Run pilot doctor and reinstall the plugin.",
            command="pilot doctor",
            exit_code=2,
        )
    )

    assert "Broken install" in rendered
    assert "Pilot hooks are not registered." in rendered
    assert "Run pilot doctor" in rendered
    assert "[bold red]" not in rendered


def test_day56_status_output_is_legible_without_rich() -> None:
    rendered = render_health_view(
        CliHealthView(
            state=SessionState.CRITICAL,
            health_score=0.24,
            fired_count=6,
            observed_signal_count=8,
        )
    )

    assert "critical" in rendered
    assert "24%" in rendered
    assert "6 fired / 8 observed" in rendered
    assert "█" in rendered
    assert "░" in rendered


def test_day56_doctor_style_table_handles_long_paths() -> None:
    rendered = render_key_value_table(
        [
            CliStatusRow("Config", "C:/Users/example/.claude/plugins/pilot/config.yaml"),
            CliStatusRow("Database", "C:/Users/example/.claude/plugins/pilot/data/pilot.sqlite3"),
            CliStatusRow("Hooks", "registered"),
        ],
        title="Pilot doctor",
        value_width=42,
    )

    assert "Pilot doctor" in rendered
    assert "Config" in rendered
    assert "Database" in rendered
    assert "Hooks" in rendered


def test_day56_writers_can_be_captured_by_tests() -> None:
    error_stream = StringIO()
    status_stream = StringIO()

    write_error(
        CliError(title="No database", message="Could not find pilot.sqlite3."),
        file=error_stream,
        use_rich=False,
    )

    write_health_view(
        CliHealthView(
            state=SessionState.WATCHING,
            health_score=0.70,
            fired_count=1,
            observed_signal_count=8,
        ),
        file=status_stream,
        use_rich=False,
    )

    assert "No database" in error_stream.getvalue()
    assert "watching" in status_stream.getvalue()
    assert "70%" in status_stream.getvalue()
