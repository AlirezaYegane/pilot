"""Pilot command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import cast

import typer
import yaml
from rich.console import Console

from pilot_core import __version__
from pilot_core.config import DEFAULT_CONFIG_PATH, load_config
from pilot_core.constants import SessionState, parse_session_state
from pilot_core.render.status import render_status_snapshot
from pilot_core.status import (
    PilotStatusSnapshot,
    build_empty_status_snapshot,
    build_status_snapshot_from_records,
    read_jsonl_records,
    status_snapshot_summary,
)

app = typer.Typer(
    name="pilot",
    help="Autopilot for Claude Code sessions.",
    no_args_is_help=True,
)
console = Console()


def _to_plain_data(value: object) -> object:
    """Convert dataclass/config-like values into YAML-safe plain data."""

    if is_dataclass(value) and not isinstance(value, type):
        data = asdict(value)
        return _to_plain_data(data)

    if isinstance(value, Mapping):
        return {str(key): _to_plain_data(item) for key, item in value.items()}

    if isinstance(value, list | tuple):
        return [_to_plain_data(item) for item in value]

    if isinstance(value, str | int | float | bool) or value is None:
        return value

    raw_dict = getattr(value, "__dict__", None)
    if isinstance(raw_dict, dict):
        return {str(key): _to_plain_data(item) for key, item in raw_dict.items()}

    return str(value)


def _config_as_dict() -> dict[str, object]:
    """Return the resolved config as a plain dictionary."""

    data = _to_plain_data(load_config())

    if isinstance(data, dict):
        return cast(dict[str, object], data)

    return {"config": data}


def _replay_case_path(case_name: str) -> Path:
    """Resolve a replay case name to a fixture path."""

    name = case_name
    if not name.endswith(".jsonl"):
        name = f"{name}.jsonl"

    return Path("tests") / "fixtures" / "replay_cases" / name


def _build_status_snapshot(
    *,
    replay_file: str | None = None,
    replay_case: str | None = None,
    state: str = SessionState.HEALTHY.value,
    session_id: str | None = None,
) -> PilotStatusSnapshot:
    """Build a status snapshot from plain values."""

    current_state = parse_session_state(state)

    replay_path: Path | None = None

    if replay_file is not None:
        replay_path = Path(replay_file)
    elif replay_case is not None:
        replay_path = _replay_case_path(replay_case)

    if replay_path is None:
        return build_empty_status_snapshot(
            current_state=current_state,
            session_id=session_id,
        )

    records = read_jsonl_records(replay_path)

    return build_status_snapshot_from_records(
        records,
        current_state=current_state,
        session_id=session_id,
        source=str(replay_path),
    )


def _build_status_snapshot_from_args(args: argparse.Namespace) -> PilotStatusSnapshot:
    """Build a status snapshot from argparse args."""

    return _build_status_snapshot(
        replay_file=args.replay_file,
        replay_case=args.replay_case,
        state=str(args.state),
        session_id=args.session_id,
    )


def _run_status(args: argparse.Namespace) -> int:
    """Run `pilot status` through argparse."""

    snapshot = _build_status_snapshot_from_args(args)

    if args.json:
        print(json.dumps(status_snapshot_summary(snapshot), indent=2, sort_keys=True))
    else:
        print(render_status_snapshot(snapshot), end="")

    return 0


@app.command()
def version() -> None:
    """Show the installed Pilot version."""

    console.print("pilot-cc 0.1.0")


@app.command()
def doctor() -> None:
    """Run a lightweight local diagnostic check."""

    console.print("[green]Pilot doctor OK[/green]")


@app.command("config-path")
def config_path() -> None:
    """Show the default Pilot config path."""

    console.print(str(DEFAULT_CONFIG_PATH))


@app.command("show-config")
def show_config() -> None:
    """Show the resolved Pilot configuration."""

    console.print(yaml.safe_dump(_config_as_dict(), sort_keys=True).strip())


@app.command("status")
def status_command(
    replay_file: str | None = typer.Option(
        None,
        "--replay-file",
        help="Read status input from a JSONL replay file.",
    ),
    replay_case: str | None = typer.Option(
        None,
        "--replay-case",
        help="Read status input from tests/fixtures/replay_cases/<case>.jsonl.",
    ),
    state: str = typer.Option(
        SessionState.HEALTHY.value,
        "--state",
        help="Current session state before status transition.",
    ),
    session_id: str | None = typer.Option(
        None,
        "--session-id",
        help="Optional session id to display.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output status as JSON.",
    ),
) -> None:
    """Show current Pilot session health, state, and signal status."""

    snapshot = _build_status_snapshot(
        replay_file=replay_file,
        replay_case=replay_case,
        state=state,
        session_id=session_id,
    )

    if json_output:
        console.print_json(json.dumps(status_snapshot_summary(snapshot), sort_keys=True))
    else:
        console.print(render_status_snapshot(snapshot), end="")


def build_parser() -> argparse.ArgumentParser:
    """Build the Pilot argparse parser."""

    parser = argparse.ArgumentParser(
        prog="pilot",
        description="Pilot CLI for monitoring coding-agent sessions.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pilot {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    status = subparsers.add_parser(
        "status",
        help="Show current Pilot session health, state, and signal status.",
    )
    status.add_argument(
        "--replay-file",
        default=None,
        help="Read status input from a JSONL replay file.",
    )
    status.add_argument(
        "--replay-case",
        default=None,
        help="Read status input from tests/fixtures/replay_cases/<case>.jsonl.",
    )
    status.add_argument(
        "--state",
        default=SessionState.HEALTHY.value,
        help="Current session state before status transition.",
    )
    status.add_argument(
        "--session-id",
        default=None,
        help="Optional session id to display.",
    )
    status.add_argument(
        "--json",
        action="store_true",
        help="Output status as JSON.",
    )
    status.set_defaults(func=_run_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run Pilot argparse CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)

    command_func = getattr(args, "func", None)
    if command_func is None:
        parser.print_help()
        return 0

    return int(command_func(args))


if __name__ == "__main__":
    sys.exit(main())
