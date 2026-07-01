from __future__ import annotations

from io import StringIO

import pytest

from pilot_core.cli_ux import (
    CliError,
    CliHealthView,
    CliMessageKind,
    CliStatusRow,
    format_cli_error,
    format_message,
    health_bar,
    health_percent,
    render_health_view,
    render_key_value_table,
    render_mapping_table,
    strip_rich_markup,
    success,
    warning,
    write_error,
    write_health_view,
)
from pilot_core.constants import SessionState


def test_health_percent_clamps_values() -> None:
    assert health_percent(1.0) == 100
    assert health_percent(0.0) == 0
    assert health_percent(1.5) == 100
    assert health_percent(-0.2) == 0


def test_health_bar_is_deterministic() -> None:
    assert health_bar(1.0, width=5) == "█████"
    assert health_bar(0.0, width=5) == "░░░░░"
    assert health_bar(0.6, width=10) == "██████░░░░"


def test_health_bar_rejects_tiny_width() -> None:
    with pytest.raises(ValueError):
        health_bar(0.5, width=3)


def test_format_cli_error_plain_text() -> None:
    rendered = format_cli_error(
        CliError(
            title="Database unavailable",
            message="Pilot could not open the local SQLite database.",
            hint="Run pilot doctor.",
            command="pilot doctor",
            exit_code=2,
        )
    )

    assert "Database unavailable" in rendered
    assert "Run pilot doctor." in rendered
    assert "pilot doctor" in rendered
    assert "Exit code: 2" in rendered


def test_format_cli_error_markup_can_be_stripped() -> None:
    rendered = format_cli_error(
        CliError(title="Bad config", message="Invalid YAML."),
        use_markup=True,
    )

    assert "[bold red]" in rendered
    assert "Bad config" in strip_rich_markup(rendered)
    assert "[bold red]" not in strip_rich_markup(rendered)


def test_message_helpers() -> None:
    assert "done" in success("done")
    assert "careful" in warning("careful")
    assert "hello" in format_message("hello", kind=CliMessageKind.INFO)


def test_render_key_value_table_truncates_long_values() -> None:
    rendered = render_key_value_table(
        [CliStatusRow("Path", "x" * 100)],
        title="Pilot doctor",
        value_width=30,
    )

    assert "Pilot doctor" in rendered
    assert "[truncated]" in rendered


def test_render_mapping_table_sorts_keys() -> None:
    rendered = render_mapping_table({"z": 1, "a": 2}, title="Map")
    assert rendered.index("a") < rendered.index("z")


def test_render_health_view_contains_core_fields() -> None:
    rendered = render_health_view(
        CliHealthView(
            state=SessionState.DEGRADING,
            health_score=0.52,
            fired_count=3,
            observed_signal_count=8,
        )
    )

    assert "Pilot status" in rendered
    assert "degrading" in rendered
    assert "52%" in rendered
    assert "3 fired / 8 observed" in rendered


def test_write_error_plain_fallback_to_file() -> None:
    stream = StringIO()

    emitted = write_error(
        CliError(title="No config", message="Config file missing."),
        file=stream,
        use_rich=False,
    )

    assert "No config" in emitted
    assert "No config" in stream.getvalue()


def test_write_health_view_plain_fallback_to_file() -> None:
    stream = StringIO()

    emitted = write_health_view(
        CliHealthView(
            state=SessionState.HEALTHY,
            health_score=0.91,
            fired_count=0,
            observed_signal_count=8,
        ),
        file=stream,
        use_rich=False,
    )

    assert "healthy" in emitted
    assert "91%" in stream.getvalue()
