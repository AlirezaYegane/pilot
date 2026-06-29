"""Command-line interface for Pilot."""

from __future__ import annotations

import typer
from rich.console import Console

from pilot_core.config import DEFAULT_CONFIG_PATH, load_config

app = typer.Typer(
    name="pilot",
    help="Autopilot for Claude Code sessions.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """Show the installed Pilot version."""
    console.print("pilot-cc 0.1.0")


@app.command()
def doctor() -> None:
    """Run a lightweight local diagnostic check."""
    load_config()
    console.print("[green]Pilot doctor OK[/green]")


@app.command("config-path")
def config_path() -> None:
    """Show the default Pilot config file path."""
    console.print(str(DEFAULT_CONFIG_PATH))


@app.command("show-config")
def show_config() -> None:
    """Show the effective Pilot configuration."""
    config = load_config()
    console.print_json(data=config.model_dump(mode="json"))


if __name__ == "__main__":
    app()
