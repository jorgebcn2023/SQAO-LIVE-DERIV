# SQAO V2.4 — Quant workflow queue isolation

## Problem addressed

The quantitative workflow used one repository-wide concurrency group. A long-running or stalled Step Index research job on an unrelated branch could therefore keep a newer pull-request validation in the `pending` state, even when its code and tests were ready.

## Change

The workflow concurrency group now includes `${{ github.ref }}`:

```yaml
concurrency:
  group: sqao-step-index-quant-${{ github.ref }}
  cancel-in-progress: false
```

Runs for the same Git ref remain serialized and are not cancelled automatically. Runs on different branches or pull requests no longer block one another.

## Scope and safety

- Workflow scheduling only; no strategy, indicator, OHLC, entry, stop, target, cost, or statistical-gate changes.
- The pipeline remains READ-ONLY / RESEARCH-ONLY and does not place orders.
- This does not bypass any research stage or treat a queued run as successful.
- A V2.4 run is validated only after the complete OHLC research, baseline checkpoint, Table 18 audit/checkpoint, strategy lab, ARIMA/Monte Carlo and final artifact validation succeed.

## Verification

Check the GitHub Actions run for this branch. Confirm that the quant workflow starts rather than waiting behind an unrelated branch's concurrency lock, then inspect the generated artifacts and their timestamps.
