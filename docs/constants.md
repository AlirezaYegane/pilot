# Pilot Constants

This document describes the stable string contracts used across Pilot.

Constants live in:

```text
pilot_core/constants.py
Why this exists

Pilot writes values into config files, JSON payloads, SQLite rows, CLI output, and future hook messages.
Because of that, raw strings must not be scattered across the codebase.

Use enums instead of magic strings.

Core enums
SessionState
healthy
watching
degrading
critical
handoff_pending
handed_off
SignalName
token_burn
repeated_calls
error_cascade
backtracking
context_saturation
self_doubt
rate_limit
low_productivity
Severity
info
warning
error
critical
ActivationMode
shadow
warn
action
HookEvent
SessionStart
UserPromptSubmit
PreToolUse
PostToolUse
PostToolUseFailure
Stop
SessionEnd
Rules
Enum values are stable public contracts.
Do not rename values without a migration plan.
Config and database code should parse strings through helper functions.
New signal names must be added to:
SignalName
DEFAULT_SIGNAL_WEIGHTS
DEFAULT_SIGNAL_ACTIVATION_MODES
tests
