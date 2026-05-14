# Architecture Decision Records

This directory contains Pilot's architecture decision records.

ADRs are stable engineering notes that explain why important project decisions exist.

## Current ADRs

| ADR | Decision |
|---|---|
| [ADR-001](ADR-001-local-first.md) | Local-first by default |
| [ADR-002](ADR-002-hook-safety.md) | Hooks must never break the user |
| [ADR-003](ADR-003-silent-failure-philosophy.md) | Silent failure philosophy |
| [ADR-004](ADR-004-hook-latency.md) | Hook latency budget |
| [ADR-005](ADR-005-runtime-path-strategy.md) | Runtime path strategy |

## Rules

- Add a new ADR for decisions that affect storage, hooks, signal semantics, safety, public contracts, or release behaviour.
- Do not rewrite accepted decisions casually.
- Prefer adding a superseding ADR when a major decision changes.
- Keep ADRs short enough to be read during code review.
