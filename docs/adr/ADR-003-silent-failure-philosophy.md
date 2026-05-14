# ADR-003: Silent failure philosophy

## Status

Accepted.

## Context

Pilot's value comes from monitoring and guiding coding-agent sessions, but it lives in a sensitive execution path. The user may be running production work, a long refactor, or a fragile debugging session. In that context, a monitoring plugin should not become the source of interruption.

A visible Pilot error is more damaging than Pilot temporarily skipping a non-critical monitoring action.

## Decision

Pilot uses a fail-silent philosophy for runtime and hook code.

When a non-critical operation fails, Pilot should:

1. catch the exception
2. write a bounded debug log entry
3. return a safe fallback
4. allow the user's session to continue

This philosophy applies especially to:

- debug logging
- path creation
- token estimation
- signal evaluation
- post-tool data collection
- handoff preparation attempts

## Consequences

Positive:

- safer hook runtime
- more reliable user experience
- lower chance of blocking Claude Code
- cleaner path to dogfooding

Trade-offs:

- failures can be less visible during development
- tests must intentionally assert failure behaviour
- debug logs and doctor commands become mandatory operational tools

## Implementation rules

- Use `run_safely` for isolated operations.
- Use `fail_silent` for hook-safe wrappers.
- Use `safe_string` before writing arbitrary objects into logs.
- Never let debug logging raise.
- Never log unbounded payloads.
- Do not swallow errors in tests unless the test is explicitly checking fail-silent behaviour.

## Verification

This decision is verified by:

- `tests/unit/test_safety.py`
- `tests/unit/test_architecture_docs.py`
- future hook tests that simulate malformed stdin
- future replay tests that simulate broken signal inputs
