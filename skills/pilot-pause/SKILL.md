---
name: pilot-pause
description: Pause risky or degraded Pilot work, stop tool-heavy loops, and give the user a safe resume point.
---

# Pilot Pause

Use this skill when the user says pause, stop, hold, slow down, wait, prevent token burn, avoid loops, or asks whether continuing is safe.

## Goal

Stop risky momentum, preserve the current state, and give the user a safe resume point.

## Safe workflow

Default behavior:

- Do not run additional tools unless needed for a quick read-only status check.
- If status is needed, run only pilot status.
- Summarise why pausing is safer.
- Give a short resume point.
- Wait for explicit user approval before continuing.

## Output format

Return:

- Pause reason
- Current known state
- What has already been done
- Risk if we continue immediately
- Safe resume point
- One recommended next action

## Safety rules

- Do not run additional tools unless the user explicitly approves.
- Do not edit files.
- Do not run destructive commands.
- Do not start a new implementation step.
- Do not continue a failing loop.
- Wait for explicit user approval before continuing.

## Resume point rules

A good resume point should say:

- which day or task is active
- which files were likely involved
- which command or test should be run next
- which failed approach should not be repeated

If the session is critical or confused, recommend using pilot-handoff before continuing.
