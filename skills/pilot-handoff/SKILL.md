---
name: pilot-handoff
description: Produce a concise manual handoff from Pilot session data and current context when the user wants to continue in a fresh session.
---

# Pilot Handoff

Use this skill when the user asks to hand off, continue in a new session, preserve progress, avoid repeating failed attempts, or create a session summary.

## Goal

Create a concise, factual handoff that helps the next session continue without losing context.

## Safe workflow

Use existing read-only CLI data when available:

- pilot status
- pilot sessions
- pilot show <session-id>

Prefer the latest relevant session unless the user names a specific session.

If a previous handoff artifact exists, use it as the primary source.

If CLI data is unavailable, create the handoff from the visible conversation context and clearly say which parts are inferred from conversation only.

## Required handoff sections

Use these sections:

- Task
- Progress
- Key Decisions
- Files Modified
- Blockers
- Next Step
- Do Not Redo

## Quality rules

- Do not invent facts.
- Do not claim a file was modified unless there is evidence.
- Do not repeat failed attempts listed in Do Not Redo.
- Make the Next Step specific and actionable.
- Keep the handoff concise.
- Prefer concrete filenames, commands, errors, and test results when available.

## Safety rules

- Do not modify project files.
- Do not run destructive commands.
- Do not create commits.
- Do not trigger new implementation work inside this skill.
- If the current session looks critical, recommend starting a fresh session after the handoff.
