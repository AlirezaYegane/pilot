# Pilot Status Command

Day 52 adds the first daily-use CLI command:

- `pilot status`

## Scope

`pilot status` renders:

- health score
- health bar
- current state to next state view
- fired signal count
- ordered signal list

## Not in scope yet

- `pilot sessions`
- `pilot show`
- `pilot budget`
- `pilot doctor`
- Rich terminal polish

Those are handled in later Week 8 days.

## Development usage

Run:

- `pilot status --replay-case degraded_session`
- `pilot status --replay-case healthy_session --json`
- `python scripts/smoke_day52_status.py`

## Design notes

The status command is intentionally built on pure modules:

- `pilot_core.status`
- `pilot_core.render.status`

The CLI is thin. It only loads records, builds a snapshot, and renders text or JSON.

## Expected behavior

Healthy sessions should show a high health score and zero fired signals.

Degraded sessions should show a low health score, a degraded or critical state,
and multiple fired signals.
