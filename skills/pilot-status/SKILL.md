---
name: pilot-status
description: Inspect current Pilot health, state, recent signals, budget pressure, and install diagnostics without changing project files.
---

# Pilot Status

Use this skill when the user asks for Pilot status, session health, degradation state, recent signals, budget pressure, or install health.

## Goal

Give the user a compact read-only status report for the current Pilot environment.

## Safe workflow

Run read-only commands only:

- pilot status
- pilot budget
- pilot doctor

If the CLI is not available, explain that Pilot CLI could not be found and suggest running the project test gate from the repository root.

## Output format

Return a short summary with these fields when available:

- State
- Health score
- Fired signals
- Budget or rate-limit pressure
- Doctor result
- Recommended next action

## Safety rules

- This skill is read-only.
- Do not edit files.
- Do not run destructive commands.
- Do not create commits.
- Do not trigger handoff generation unless the user explicitly asks for handoff.
- Do not hide degraded or critical status from the user.
- If diagnostics fail, report the failure clearly and keep the session safe.

## Interpretation rules

Healthy means the session can continue normally.

Watching means continue carefully.

Degrading means suggest summarising progress or reducing tool-heavy work.

Critical means recommend handoff or pause before continuing.

If budget pressure is high, tell the user before running any expensive follow-up workflow.
