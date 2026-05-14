# ADR-005: Runtime path strategy

## Status

Accepted.

## Context

Pilot needs stable local paths for runtime data before the SQLite storage layer is implemented.

Runtime paths include:

- data directory
- handoff directory
- temporary directory
- debug log path
- SQLite database path

If path construction is scattered across modules, future hooks, storage code, and CLI commands will drift and become hard to test.

## Decision

Pilot centralises runtime path resolution in `pilot_core/paths.py`.

The resolved path object is `RuntimePaths`.

It owns:

- `data_dir`
- `handoff_dir`
- `temp_dir`
- `debug_log_path`
- `db_path`

Directories are created through `ensure_runtime_dirs`.

## Consequences

Positive:

- predictable local runtime layout
- easier testing with temporary directories
- cleaner future storage layer
- fewer hard-coded paths
- better compatibility with config overrides

Trade-offs:

- modules must depend on the path helper instead of constructing paths directly
- config/path integration must remain stable

## Implementation rules

- Storage code must use `resolve_runtime_paths`.
- Hook code must not hard-code runtime directories.
- Handoff code must use `RuntimePaths.handoff_dir`.
- Temporary files must live under `RuntimePaths.temp_dir`.
- Debug logs must use `RuntimePaths.debug_log_path`.
- SQLite must default to `RuntimePaths.db_path`.

## Verification

This decision is verified by:

- `tests/unit/test_paths.py`
- `tests/unit/test_architecture_docs.py`
- future SQLite bootstrap tests
