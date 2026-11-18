# SQAO LIVE DERIV V3.2.0 — Visual Integration Branch

Branch: `feature/sqao-v3.2.0-visual-integration`

## Scope delivered in this branch

- Adds `ENGINE/chart_visual_intelligence_v32.py` as a fail-closed screenshot evidence intake module.
- Preserves SHA-256, filename, supplied timeframe, supplied capture timestamp, OCR tokens, confidence and bounding boxes.
- Emits explicit `NOT_AVAILABLE` / `LOW_CONFIDENCE` indicator states instead of fabricating values.
- Never reconstructs OHLC from screenshot pixels.
- Adds MTF completeness and capture timestamp metadata checks.
- Adds regression tests and registers them in `.github/workflows/test.yml`.

## Indicator recognition boundary

The current branch detects OCR labels for EMA, Bollinger, RSI, MACD, ADX, +DI, -DI and Stochastic. A detected label is not a numeric indicator reading. Values remain unavailable until the system can associate a numeric token or a segmented curve with the correct indicator panel, legend, parameters and scale.

This is intentionally conservative. It prevents an OCR token from being misattributed to the wrong indicator.

## MTF synchronization boundary

The metadata gate requires six frames and explicit capture timestamps. A matching screenshot timestamp is only a metadata check; it does not prove that each chart displays the same last closed candle. Full synchronization still requires symbol identity, timeframe granularity, candle-close epoch and data freshness from the quantitative API.

## Integration contract for the next stage

Every observation must retain:
- `provenance`: `VISUAL_RAW`, `API_RAW`, `DERIVED` or `INFERENCE`.
- `status`: `EXACT_READ`, `VISUAL_ESTIMATE`, `NOT_AVAILABLE` or `LOW_CONFIDENCE`.
- `value`, `unit`, `parameters`, `applied_price`, `timeframe`, `symbol`.
- `source_file`, `sha256`, `capture_timestamp`, `bbox`, `confidence`.
- API reconciliation result: `MATCH`, `MISMATCH`, `NOT_COMPARABLE`, `UNALIGNED` or `STALE`.

The API and image intake must remain separate read-only inputs. No order endpoint, account endpoint or trade execution is permitted.

## Validation

Run locally:

```bash
python -m compileall -q ENGINE
python -m ENGINE.test_chart_visual_intelligence_v32
python -m ENGINE.test_chart_visual_extraction
python -m ENGINE.test_mtf_sync
```

The GitHub Actions test workflow includes the new regression test. A successful commit or branch creation is not evidence that CI passed; inspect the Actions run before merging.

## Current safety decision

`READ_ONLY=true`, `RESEARCH_ONLY=true`, `decision=NO_TRADE`, `execution_eligible=false`.

This branch is an integration checkpoint, not a claim that full curve recognition, numeric indicator extraction, API reconciliation or deployment is complete.
