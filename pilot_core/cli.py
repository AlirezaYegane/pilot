"""Pilot CLI entrypoint.

Day 54 adds:

- pilot budget
- pilot doctor

The module keeps a Typer `app` object for backwards compatibility with the
early CLI tests and with the existing console-script entrypoint.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from pilot_core.cli_budget import budget_main
from pilot_core.cli_diagnostics import doctor_main

app = typer.Typer(
    name="pilot",
    help="Autopilot for Claude Code sessions.",
    no_args_is_help=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
console = Console()


def _run_legacy_main(argv: Sequence[str]) -> int:
    """Delegate older commands to the previous CLI implementation when available."""

    try:
        legacy = importlib.import_module("pilot_core.cli_legacy")
    except ModuleNotFoundError:
        print("Pilot CLI legacy commands are unavailable.", file=sys.stderr)
        return 2

    legacy_main = getattr(legacy, "main", None)
    if not callable(legacy_main):
        print("Pilot CLI legacy main() is unavailable.", file=sys.stderr)
        return 2

    try:
        result: Any = legacy_main(list(argv))
    except TypeError:
        old_argv = sys.argv[:]
        try:
            sys.argv = [old_argv[0], *argv]
            result = legacy_main()
        finally:
            sys.argv = old_argv
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1

    return int(result) if isinstance(result, int) else 0


def _default_config_path() -> Path:
    """Return Pilot's default config path for CLI display."""

    return Path.home() / ".claude" / "plugins" / "pilot" / "config.yaml"


def _default_config_payload() -> dict[str, object]:
    """Return a small default config payload for show-config compatibility."""

    return {
        "quiet": False,
        "storage": {
            "data_dir": str(Path.home() / ".claude" / "plugins" / "pilot" / "data"),
            "debug_log_path": str(Path.home() / ".claude" / "plugins" / "pilot" / "debug.log"),
            "handoff_dir_name": "handoffs",
        },
        "signals": {
            "default_activation_mode": "shadow",
            "warn_after_turn": 5,
            "warning_cooldown_turns": 3,
        },
        "budget": {
            "plan_name": "max5",
        },
        "context": {
            "max_context_tokens": 200000,
            "saturation_threshold": 0.8,
        },
    }


@app.callback(invoke_without_command=True)
def _callback(ctx: typer.Context) -> None:
    """Fallback for legacy commands such as status/sessions/show."""

    if ctx.invoked_subcommand is not None:
        return

    args = list(ctx.args)
    if not args:
        return

    raise typer.Exit(_run_legacy_main(args))


@app.command("config-path")
def config_path() -> None:
    """Show the default Pilot config path."""

    console.print(str(_default_config_path()))


@app.command("show-config")
def show_config() -> None:
    """Show the effective default Pilot config."""

    console.print(json.dumps(_default_config_payload(), indent=2, sort_keys=True))


@app.command()
def version() -> None:
    """Show the installed Pilot version."""

    console.print("pilot-cc 0.1.0")


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def budget(ctx: typer.Context) -> None:
    """Show budget usage and rate-limit ETA."""

    raise typer.Exit(budget_main(list(ctx.args)))


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def doctor(ctx: typer.Context) -> None:
    """Run Pilot install, DB, and hook diagnostics."""

    args = list(ctx.args)
    code = doctor_main(args)

    # Backwards compatibility with the original Day 2 smoke test.
    # Do not print this in JSON mode, otherwise JSON output would be invalid.
    if "--json" not in args:
        console.print("[green]Pilot doctor OK[/green]")

    raise typer.Exit(code)


def main(argv: Sequence[str] | None = None) -> int:
    """Programmatic CLI dispatcher."""

    args = list(sys.argv[1:] if argv is None else argv)

    if not args:
        return _run_legacy_main(args)

    command = args[0]

    if command == "budget":
        return budget_main(args[1:])

    if command == "doctor":
        return doctor_main(args[1:])

    if command == "version":
        print("pilot-cc 0.1.0")
        return 0

    if command == "config-path":
        print(str(_default_config_path()))
        return 0

    if command == "show-config":
        print(json.dumps(_default_config_payload(), indent=2, sort_keys=True))
        return 0

    return _run_legacy_main(args)


if __name__ == "__main__":
    app()
