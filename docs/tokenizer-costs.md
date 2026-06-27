# Tokenizer and Cost Helpers

Day 50 starts Week 8: Budget + CLI + skills.

## Purpose

Day 50 adds the foundation for later budget tracking: safe payload stringification, token estimation, and cost estimation helpers.

Day 51 will build budget ETA, daily/weekly usage views, and rate-limit integration on top of this layer.

## Main files

<div dir="ltr">

| File | Purpose |
|---|---|
| `pilot_core/tokenizer.py` | Safe stringify, token estimates, cost estimates |
| `tests/unit/test_tokenizer.py` | Unit tests for helper behavior |
| `tests/integration/test_day50_tokenizer_costs.py` | Replay fixture coverage |
| `scripts/smoke_day50_tokenizer_costs.py` | Human-readable smoke report |

</div>

## Main API

<div dir="ltr">

| Function / Type | Purpose |
|---|---|
| `safe_stringify()` | Convert arbitrary payloads into bounded safe text |
| `stringify_payload()` | Return safe text plus metadata |
| `estimate_text_tokens()` | Estimate tokens for one payload |
| `estimate_payload_tokens()` | Estimate input/output/total tokens |
| `estimate_record_tokens()` | Estimate replay/hook record tokens |
| `estimate_records_tokens()` | Aggregate token estimates over many records |
| `ModelPricing` | Explicit per-million-token pricing |
| `estimate_cost()` | Estimate USD cost from token counts |
| `estimate_payload_cost()` | Estimate cost from token estimates |

</div>

## Design rules

- The module is pure and side-effect free.
- It does not read SQLite.
- It does not call hooks.
- It does not decide budget policy.
- It uses `tiktoken` when available.
- It falls back to approximate character-based estimation when `tiktoken` is unavailable.
- Cost estimation is not billing authority; pass explicit pricing for exact calculations.

## Token estimation flow

```text
arbitrary payload
  -> safe_stringify()
  -> tiktoken if available
  -> approximate fallback if unavailable
  -> PayloadTokenEstimate
```

## Cost estimation flow

```text
PayloadTokenEstimate / TokenTotals
  -> explicit ModelPricing
  -> estimate_payload_cost()
  -> TokenCostEstimate
```

## Smoke command

```powershell
python scripts\smoke_day50_tokenizer_costs.py
```

## Next day

Day 51 should build budget ETA, daily/weekly usage views, and rate-limit proximity integration on top of these helpers.
