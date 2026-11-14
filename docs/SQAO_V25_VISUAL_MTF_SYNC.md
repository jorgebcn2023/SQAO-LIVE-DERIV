# SQAO V2.5 — Visual Intelligence & MTF Synchronization

## Purpose
Extend the existing V2.1 screenshot extraction layer without creating a duplicate OCR implementation. V2.5 adds a fail-closed synchronization audit between uploaded chart timeframes and the quantitative market snapshot.

## What the source PDF contributes
The user-provided Optimización Operativa Step Index (8 pages) proposes a six-timeframe hierarchy (D1, H4, H1, M15, M5, M1), weighted directional scoring, MACD signal-line versus zero-line interpretation, pullback/rejection entry planning, partial exits, ATR trailing-stop concepts and risk sizing.

These are research hypotheses, not validated performance results. The PDF's 83.25% sell score is a weighted opinion score, not a calibrated probability. Its 65% assumed win rate is not an observed backtest statistic and must not be used to calculate production expectancy or Kelly sizing. The AMD/SMC/liquidity-sweep narrative is not directly observable from public OHLC alone, especially without an order book. Assertions of zero slippage/gaps and contract-value assumptions require independent Deriv/broker verification. Price levels in the PDF belong to its chart snapshot and are not current executable quotes.

## V2.5 changes
- ENGINE/mtf_sync.py: common-snapshot timestamp and per-timeframe freshness gate.
- Missing quantitative frame, missing timestamp, stale candle, future candle or clock-skew condition blocks the gate.
- Screenshot x-axis labels are never treated as timestamped OHLC.
- A blocked gate returns decision_override=NO_TRADE.
- The gate is a data-integrity control, not a BUY/SELL predictor and not a probability.

## Default requirements
When six timeframes are supplied, require D1/H4/H1/M15/M5/M1. Freshness defaults to no more than two candle durations relative to the common snapshot timestamp. A caller may pass an exact uploaded subset for diagnostics, but a production six-timeframe analysis must require all six.

## Integration
AI/gpt_vision.py runs the gate against the quantitative snapshot and includes its output in the vision prompt. If blocked, visual bias cannot be promoted into an actionable entry; final status is NO_TRADE or WAIT pending fresh synchronized OHLC.

## Validation
Run:
- python -m ENGINE.test_mtf_sync
- python -m ENGINE.test_chart_visual_extraction
- python -m ENGINE.test_chart_indicator_audit

## Safety
READ-ONLY / RESEARCH-ONLY. No proposal, buy, sell, modify, close, EA or broker order endpoint is added. Historical evidence, cost verification and the existing out-of-sample acceptance gate remain mandatory.
