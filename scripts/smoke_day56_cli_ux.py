"""Day 56 CLI UX smoke report."""

from __future__ import annotations

import json

from pilot_core.cli_ux import (
    CliError,
    CliHealthView,
    CliStatusRow,
    format_cli_error,
    render_health_view,
    render_key_value_table,
    rich_is_available,
    success,
    warning,
)
from pilot_core.constants import SessionState


def main() -> int:
    """Print a small deterministic CLI UX smoke report."""

    healthy = render_health_view(
        CliHealthView(
            state=SessionState.HEALTHY,
            health_score=0.92,
            fired_count=0,
            observed_signal_count=8,
        )
    )

    degraded = render_health_view(
        CliHealthView(
            state=SessionState.DEGRADING,
            health_score=0.47,
            fired_count=4,
            observed_signal_count=8,
        )
    )

    doctor = render_key_value_table(
        [
            CliStatusRow("Config", "ok"),
            CliStatusRow("Database", "ok"),
            CliStatusRow("Hooks", "registered"),
            CliStatusRow("Skills", "registered"),
        ],
        title="Pilot doctor",
    )

    error = format_cli_error(
        CliError(
            title="Hook registration missing",
            message="Pilot could not find hooks/hooks.json in the plugin root.",
            hint="Run pilot doctor, then reinstall the plugin.",
            command="pilot doctor",
            exit_code=2,
        )
    )

    report = {
        "rich_available": rich_is_available(),
        "healthy_contains_bar": "█" in healthy,
        "degraded_contains_state": "degrading" in degraded,
        "doctor_contains_hooks": "Hooks" in doctor,
        "error_contains_hint": "Run pilot doctor" in error,
        "success_message": success("CLI UX smoke passed"),
        "warning_message": warning("This is a terminal-safe warning"),
    }

    print(healthy)
    print()
    print(degraded)
    print()
    print(doctor)
    print()
    print(error)
    print()
    print(json.dumps(report, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
