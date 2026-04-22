# ADR-003: Performance-sensitive hook design

Status: Accepted

Pre-hooks must stay extremely lightweight.
Heavy work moves to post-hooks or async paths.

Why:
- Keep latency invisible
- Prevent uninstall risk
