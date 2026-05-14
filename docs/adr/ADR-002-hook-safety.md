# ADR-002: Hooks must never break the user

## Status

Accepted.

## Context

Pilot runs inside a user's coding-agent workflow. Hook scripts may execute before or after tool calls. A broken hook can damage user trust immediately if it blocks a normal coding session, fails loudly, or causes confusing tool behaviour.

The core product rule is simple:

Pilot is allowed to fail quietly, but it is not allowed to break the user's active session.

## Decision

All Pilot hooks must be designed with a never-break-the-user policy.

Hook failures must:

- be caught
- be logged locally where possible
- return a safe exit code
- avoid user-facing tracebacks
- avoid blocking normal agent work unless an explicit future safety policy requires it

For v0.1, unexpected hook errors must exit successfully rather than block the user's action.

## Consequences

Positive:

- lower uninstall risk
- safer dogfooding
- less chance of interrupting real coding sessions
- easier adoption by cautious users

Trade-offs:

- silent failures can hide bugs during development
- debug logs become important
- doctor commands and tests must catch broken installs

## Implementation rules

- Hook entrypoints must wrap non-trivial work in fail-silent helpers.
- Unexpected exceptions must go through `log_exception`.
- Debug logging must itself be fail-silent.
- Hook code must avoid broad stdout noise.
- Stdout should be reserved for hook control JSON when needed.
- Pre-hook logic must stay minimal and predictable.

## Verification

This decision is verified by:

- `tests/unit/test_safety.py`
- `tests/unit/test_architecture_docs.py`
- future hook smoke tests
- future `pilot doctor` diagnostics
