# ADR-004: Hook latency budget

## Status

Accepted.

## Context

Claude Code hooks run during the user's active workflow. Some hooks are synchronous and can directly add latency before a tool call proceeds. A slow monitoring plugin will feel broken even if it is technically correct.

Pilot's original performance goal is that hooks should feel invisible.

## Decision

Pilot separates hook work into latency-sensitive and latency-tolerant paths.

Synchronous pre-hook work must stay minimal.

Post-hook and asynchronous paths may do more work, but they still need bounded runtime and safe failure behaviour.

Target budgets for v0.1:

- PreToolUse p95: under 30ms
- PostToolUse p95: under 80ms
- Other lightweight hooks: under 50ms where practical

## Consequences

Positive:

- better user experience
- fewer uninstall triggers
- clearer engineering boundaries
- easier benchmark design

Trade-offs:

- some signal evaluation may need delayed processing
- token estimation must be efficient
- storage calls must stay lightweight

## Implementation rules

- PreToolUse must avoid heavy tokenization.
- PreToolUse must avoid network calls.
- PreToolUse must avoid large database scans.
- Heavy signal evaluation belongs in post-tool or replay paths.
- Hook benchmarks must exist before claiming performance improvements.
- Future blocking policies must be carefully benchmarked.

## Verification

This decision is verified by:

- future tests/benchmarks
- future scripts/bench_hooks.py
- future integration smoke tests
- tests/unit/test_architecture_docs.py
