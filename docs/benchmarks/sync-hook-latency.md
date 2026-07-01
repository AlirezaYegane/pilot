# Sync Hook Latency Benchmarks

Day 57 adds a subprocess benchmark suite for synchronous Claude Code hooks.

## Why this matters

Synchronous hooks add user-facing latency. Pilot must keep them lightweight, fail-silent, and predictable.

## Scope

- Load hook commands from `hooks/hooks.json`
- Select hooks that are not marked with `async: true`
- Run each hook as a Python subprocess with a minimal synthetic payload
- Measure p50, p95, min, max, and mean latency
- Validate that stdout is either empty or valid JSON
- Check that hooks exit with code 0
- Run a lightweight static audit for obvious heavy imports and IO patterns

## Important note

This benchmark measures subprocess latency, not only pure Python function latency. On Windows, process startup can dominate the number. The goal is regression detection and hot-path evidence, not claiming sub-50ms cold subprocess startup.

## Manual command

```powershell
python scripts\bench_day57_sync_hooks.py --iterations 20 --warmups 2 --p95-budget-ms 2000
```

## Fast CI smoke

```powershell
pytest tests\benchmarks\test_day57_sync_hook_latency.py
```

## Interpreting output

- `p95_ms`: 95th percentile subprocess latency
- `exit_code_failures`: hook violated fail-silent behavior
- `stdout_json_failures`: hook wrote invalid control output to stdout
- `static_audit.heavy_import_hits`: possible imports to avoid in sync hooks
- `static_audit.io_hits`: possible IO to inspect in sync hooks

## Day 57 acceptance criteria

- Benchmark script runs locally
- Benchmark smoke test passes
- Sync hooks exit 0
- Sync hook stdout remains hook-safe
- p95 budget is explicit in the report
- Full project quality gate remains green
