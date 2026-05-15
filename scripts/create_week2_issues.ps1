$ErrorActionPreference = "Stop"

$issues = @(
  @{
    Title = "Define SQLite schema v1"
    Labels = "storage,database,week-2"
    Body = @"
## Goal

Create the initial SQLite schema for Pilot.

## Acceptance criteria

- [ ] `sessions` table is defined
- [ ] `turns` table is defined
- [ ] `tool_uses` table is defined
- [ ] `signals` table is defined
- [ ] `alerts` table is defined
- [ ] Required indexes are documented
- [ ] Schema is covered by tests
"@
  },
  @{
    Title = "Add migration and bootstrap system"
    Labels = "storage,database,week-2"
    Body = @"
## Goal

Create a small migration system that can initialize and upgrade the local Pilot database.

## Acceptance criteria

- [ ] Database can be created from scratch
- [ ] Migrations are idempotent
- [ ] Schema version is tracked
- [ ] WAL mode is enabled
- [ ] Busy timeout is configured
- [ ] Tests use temporary database paths
"@
  },
  @{
    Title = "Implement session and turn repositories"
    Labels = "storage,week-2"
    Body = @"
## Goal

Implement repository methods for session and turn lifecycle records.

## Acceptance criteria

- [ ] Create session
- [ ] End session
- [ ] Get session by id
- [ ] Update session state
- [ ] Create turn
- [ ] End turn
- [ ] Increment turn tool count
- [ ] Increment turn error count
- [ ] Unit tests cover normal and missing-row cases
"@
  },
  @{
    Title = "Implement tool-use and signal repositories"
    Labels = "storage,signals,week-2"
    Body = @"
## Goal

Implement storage APIs for tool-use events and signal events.

## Acceptance criteria

- [ ] Record successful tool use
- [ ] Record failed tool use
- [ ] Query recent tool hashes
- [ ] Query recent tool outcomes
- [ ] Record signal evaluation
- [ ] Query signal history
- [ ] Tests cover ordering and limits
"@
  },
  @{
    Title = "Add storage benchmark and Week 2 closeout report"
    Labels = "storage,benchmark,week-2"
    Body = @"
## Goal

Add a simple benchmark for local SQLite hot paths and document the Week 2 result.

## Acceptance criteria

- [ ] Benchmark script runs locally
- [ ] Insert/select timing is reported
- [ ] No benchmark writes into real runtime paths
- [ ] Week 2 storage closeout doc is added
"@
  }
)

foreach ($issue in $issues) {
  gh issue create `
    --title $issue.Title `
    --body $issue.Body `
    --label $issue.Labels
}
