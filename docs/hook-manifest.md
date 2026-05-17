# Claude Plugin and Hook Manifest

Day 15 wires Pilot into the Claude Code plugin shape.

## Files

- .claude-plugin/plugin.json
- hooks/hooks.json

## Registered hook events

- SessionStart
- UserPromptSubmit
- PreToolUse
- PostToolUse
- PostToolUseFailure
- Stop
- SessionEnd

## Design rules

- PreToolUse stays synchronous because it may eventually return control JSON.
- UserPromptSubmit, PostToolUse, and PostToolUseFailure are async to reduce user-facing latency.
- Every hook command points to a stable script path under CLAUDE_PLUGIN_ROOT/hooks.
- Timeouts are intentionally short and bounded.
- Day 15 only wires the manifest. Real hook behaviour starts on Day 16.

## Validation

Run this command:

    python scripts\validate_hook_manifest.py

Expected output:

    Pilot hook manifest validation passed.

## Day 15 acceptance criteria

- plugin.json exists and contains required plugin metadata.
- hooks.json registers all seven supported hook events.
- Every hook command points to an existing script.
- Tool hooks use a global matcher.
- PreToolUse is not async.
- Post-event hooks are async where possible.
- Manifest validation passes.
- Unit tests pass.
