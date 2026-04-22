# ADR-002: Hooks must never break the user

Status: Accepted

Any hook failure must fail silently and never interrupt the user session.

Why:
- User trust
- Zero-friction operation
- Plugin should degrade gracefully
