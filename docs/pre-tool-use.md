# Day 18: PreToolUse Hook

Day 18 implements the first synchronous tool gate in Pilot.

## Purpose

`hooks/pre_tool_use.py` runs before a Claude Code tool call.

Because this hook is synchronous, it must stay small and fast.

## What it does

- Reads hook JSON from stdin
- Normalises the session id, tool name, and tool input
- Computes a stable tool-input fingerprint
- Performs tiny read-only SQLite checks
- Warns if the exact tool call/input appears to be repeating
- Optionally blocks only when emergency blocking is explicitly enabled

## What it does not do

- No heavy signal engine
- No token counting
- No writes to SQLite
- No long-running analysis
- No network calls

## Safety model

By default, the hook is non-blocking.

It may print `additionalContext` when a lightweight warning is useful.

Blocking is opt-in through:

PILOT_PRETOOL_BLOCK=1

## Why this matters

PreToolUse is on the hot path before every tool call. The hook must protect the user from loops without becoming a latency or reliability risk itself.
