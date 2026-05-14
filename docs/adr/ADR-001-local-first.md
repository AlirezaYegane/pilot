# ADR-001: Local-first by default

## Status

Accepted.

## Context

Pilot monitors coding-agent sessions, hook activity, degradation signals, token usage, and handoff metadata.

This data can include sensitive workflow information, file paths, command names, failure patterns, and project-specific context. The product promise is strongest when users can trust that core monitoring works without sending operational data to a remote service.

The original product principles are:

- zero-configuration
- zero-overhead
- never break the user
- local-first

## Decision

Pilot stores core runtime data locally by default.

The default runtime location is:

- ~/.claude/plugins/pilot/

The default data directory is:

- ~/.claude/plugins/pilot/data

Core runtime state includes:

- pilot.db
- handoffs/
- tmp/
- debug.log

No cloud service is required for:

- hook execution
- session tracking
- signal evaluation
- handoff preparation
- debug logging
- CLI status views

## Consequences

Positive:

- stronger privacy posture
- simpler installation
- fewer external failure modes
- easier offline development
- better fit for open-source trust

Trade-offs:

- multi-machine sync is not automatic
- team features will need explicit export/share design later
- local database migration quality becomes important

## Implementation rules

- Runtime paths must be resolved through pilot_core.paths.
- No module should hard-code ~/.claude/plugins/pilot.
- Local directories must be created through ensure_runtime_dirs.
- Future cloud or sharing features must be opt-in, never required for core functionality.
- SQLite remains the default storage backend for v0.1.

## Verification

This decision is verified by:

- tests/unit/test_paths.py
- tests/unit/test_architecture_docs.py
- future storage tests for SQLite bootstrap
