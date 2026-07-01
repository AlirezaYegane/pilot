# Pilot Skills

Day 55 adds the three Claude-facing skills used by the Pilot plugin.

## Skills

### pilot-status

Read-only status inspection.

Expected use:

- inspect health
- inspect current state
- inspect fired signals
- inspect budget pressure
- run install diagnostics

Allowed read-only CLI commands:

- pilot status
- pilot budget
- pilot doctor

### pilot-handoff

Manual handoff creation.

Expected use:

- preserve current task
- summarise progress
- record decisions
- list blockers
- provide next step
- prevent repeated failed work

Allowed read-only CLI commands:

- pilot status
- pilot sessions
- pilot show <session-id>

The generated handoff should include:

- Task
- Progress
- Key Decisions
- Files Modified
- Blockers
- Next Step
- Do Not Redo

### pilot-pause

Safe pause behavior.

Expected use:

- stop tool-heavy loops
- pause degraded work
- preserve a resume point
- wait for explicit user approval before continuing

Allowed read-only CLI command:

- pilot status

## Safety contract

All Day 55 skills must obey these rules:

- do not edit project files
- do not run destructive commands
- do not create commits
- do not hide degraded or critical state
- do not invent handoff facts
- do not continue after pause without explicit user approval

## Relationship to Week 8

Day 52 to Day 54 created the CLI surface.

Day 55 adds the skill layer that tells Claude how to use that CLI safely.

Day 56 will polish terminal UX, richer errors, and final CLI presentation.
