# Day 56 — CLI Polish

Day 56 adds a shared terminal UX layer for Pilot CLI commands.

## Scope

This day improves presentation only:

- Rich-powered output when Rich is installed
- deterministic plain-text fallback
- health bars
- consistent error messages
- key/value tables for status, doctor, and budget-style output
- safe traceback polish for CLI entrypoints

## Non-goals

Day 56 does not change:

- signal thresholds
- health scoring
- handoff generation
- hook behavior
- budget calculations
- storage schema

## Design

The core module is `pilot_core.cli_ux`.

It avoids direct Rich imports. Instead, it uses optional dynamic imports so the CLI still works even when Rich is unavailable.

This keeps the UX layer safe for:

- tests
- clean installs
- CI
- local developer terminals
- future hook-adjacent commands

## Main helpers

- `CliError`
- `CliHealthView`
- `CliStatusRow`
- `format_cli_error`
- `render_health_view`
- `render_key_value_table`
- `write_error`
- `write_health_view`
- `install_cli_traceback`

## Expected behavior

Healthy status output should be compact and readable.

Degraded or critical status output should make state and health obvious.

Doctor-style output should make broken installs easy to understand.

Errors should include:

- title
- message
- optional hint
- optional command
- exit code

## Quality gate

Day 56 must pass:

- ruff
- mypy
- unit tests
- integration tests
- smoke script
- full pytest
- pre-commit
