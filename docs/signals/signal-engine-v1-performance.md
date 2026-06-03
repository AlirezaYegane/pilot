# Signal Engine v1 Performance

Day 28 adds a benchmarkable Signal Engine v1 hot path.

## Scope

Signal Engine v1 currently evaluates:

- `repeated_calls`
- `error_cascade`
- `token_burn`
- `context_saturation`

The goal is not to optimize prematurely. The goal is to keep the current signal bundle cheap enough for hook-driven use.

## Policy

- Signal evaluation must stay pure and in-process.
- No network calls are allowed in signal evaluation.
- Avoid avoidable disk IO inside signal functions.
- Keep expensive work out of synchronous hooks.
- Use replay fixtures to detect regressions.

## Benchmark command

```powershell
python scripts\bench_day28_signal_engine.py --iterations 1000
```

Compact JSON output:

```powershell
python scripts\bench_day28_signal_engine.py --iterations 1000 --json
```

## Default budget

The Day 28 in-process benchmark uses:

```text
p95 <= 10 ms
```

This is stricter than what the current pure Python signal functions should need, but still loose enough to avoid noise on normal developer machines.

## Relation to hook latency

The project-level hook policy is stricter for synchronous hooks: `PreToolUse` must stay very light, and heavier signal sweeps should happen in async post-hooks.

Signal Engine v1 benchmark measures only signal computation. It does not include Python process startup, JSON stdin parsing, SQLite reads, or hook subprocess overhead.

## Regression rule

If this benchmark slows down significantly, do not guess. Inspect:

- repeated JSON serialisation
- unnecessary imports inside tight loops
- fixture size growth
- avoidable object conversion
- disk IO added to signal modules

Do not claim performance improvement without benchmark output.
