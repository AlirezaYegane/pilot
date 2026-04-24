"""Command-line interface for Pilot."""

from __future__ import annotations

import typer
from rich.console import Console

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
    console.print("[green]Pilot doctor OK[/green]")


if __name__ == "__main__":
    app()
