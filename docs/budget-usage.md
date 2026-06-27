# Budget Usage and ETA

Day 51 adds the pure budget usage layer for Pilot.

## Scope

- Daily usage view
- Weekly usage view
- Remaining token estimates
- Rate-limit ETA integration
- Serialisable budget report summaries

## Not in scope yet

- CLI command rendering
- SQLite usage aggregation
- User-facing terminal UI
- Hook enforcement

Those are handled later by the CLI and hook integration days.

## Inputs

Budget events can come from hook records, replay fixtures, or future SQLite queries.

Supported fields:

- `total_tokens`
- `input_tokens`
- `output_tokens`
- `timestamp_ms`
- `cost_usd`
- `model_name` or `model`
- `current_used_tokens` for plan-level usage

## Views

### Daily view

The daily view summarises timestamped events inside the local day window.

### Weekly view

The weekly view uses a Monday-based week window.

### ETA

ETA is delegated to the existing `rate_limit` signal so Pilot has one source of truth for rate-limit proximity.

## Design notes

- This module is pure and side-effect free.
- It does not read SQLite directly.
- It does not print or call hooks.
- Later CLI commands can safely consume `budget_report_summary()`.

## Expected behavior

Healthy replay sessions should produce usage summaries without budget warnings.

Degraded replay sessions with high `current_used_tokens` should show rate-limit pressure.

## Quality gate

Day 51 must pass:

- `ruff`
- `mypy`
- unit tests
- integration replay test
- smoke script
- `pre-commit run --all-files`
