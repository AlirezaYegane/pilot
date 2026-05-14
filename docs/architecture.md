# Pilot Architecture Overview

Pilot is a local-first monitoring and handoff layer for Claude Code sessions.

The core loop is:

```text
Claude Code hook event
        ↓
Pilot hook script
        ↓
safe runtime wrapper
        ↓
storage / signal / decision layer
        ↓
optional warning or handoff context
Design principles

Pilot follows four non-negotiable principles:

Zero-configuration by default
Low runtime overhead
Never break the user's active session
Local-first storage
Main modules
ModuleResponsibility
pilot_core.configLoad defaults, config file values, and environment overrides
pilot_core.constantsStable enums and string contracts
pilot_core.pathsResolve local runtime paths
pilot_core.safetyFail-silent execution and debug logging
pilot_core.storageFuture SQLite access layer
pilot_core.signalsFuture degradation signal implementations
pilot_core.state_machineFuture session state transitions
pilot_core.decision_engineFuture health scoring and policy decisions
pilot_core.handoffFuture handoff generation
pilot_core.cliCLI entrypoint
Runtime data

Default runtime data lives under:

~/.claude/plugins/pilot/

Important paths:

~/.claude/plugins/pilot/data/pilot.db
~/.claude/plugins/pilot/data/handoffs/
~/.claude/plugins/pilot/data/tmp/
~/.claude/plugins/pilot/debug.log
Hook safety

Hook code must be safe by default.

Unexpected runtime failures should be:

caught → logged locally → converted to safe fallback → user session continues
ADR map

Architecture decisions are documented in:

docs/adr/

Start with:

ADR-001: Local-first by default
ADR-002: Hooks must never break the user
ADR-003: Silent failure philosophy
ADR-004: Hook latency budget
ADR-005: Runtime path strategy
