# SQAO Chart Indicator Audit V2.0

**Module:** `ENGINE/chart_indicator_audit.py`  
**Version:** 2.0.0  
**Mode:** research-only / READ-ONLY  
**Input:** closed Deriv OHLC candles; never screenshot-derived prices.

## Scope

Audits H4, H1, M15, M5 and M1. Default timeframe weights are H4=3, H1=2, M15=2, M5=1 and M1=1.

## Indicator definitions

- EMA 9/20/50: seeded with the initial-period SMA, then standard recursive EMA.
- RSI(14): Wilder smoothing.
- ATR(14): Wilder-smoothed true range.
- ADX(14), +DI and -DI: Wilder-smoothed directional movement and true range.
- MACD(12,26,9): EMA fast minus EMA slow, with EMA signal and histogram.
- Bollinger(20,2): population standard deviation, with width and %B.
- Stochastic(14,3,3): fast %K, slow %K and slow %D.

## Confluence model

Four vote families are counted once per timeframe: EMA trend stack, MACD histogram, combined RSI/Stochastic oscillator, and ADX/DI directional strength. Bollinger and ATR are diagnostics only. Missing families are marked UNAVAILABLE and excluded from the denominator; they are not silently treated as neutral.

The default decision gate requires at least 60% weighted indicator coverage and a directional score margin of at least 12%. A failed coverage or margin gate returns `NO_DIRECTIONAL_EDGE`. Scores are descriptive, not probabilities or win rates.

## Data quality and safety

Input OHLC rows are checked for finite values and valid high/low envelopes. Duplicate epochs are collapsed deterministically; rows are chronologically ordered. Invalid-row and duplicate counts are included in each timeframe's `data_quality`. Only closed bars supplied by the caller may be used. Unlabelled screenshot panes remain unidentified. The module has no order-placement code.

## Integration

`ENGINE/step_index_strategy_lab.py` consumes this component and publishes its audit to the strategy report JSON and PDF. Tables 17 and 18 include the aggregate confluence; the PDF adds timeframe-level values, coverage, directional margin and input-quality counts.

## Tests

Run:

```bash
python -m ENGINE.test_chart_indicator_audit
python -m ENGINE.test_step_index_quant
```

Version 2.0 is not considered production-validated until the repository's CI workflow passes on the final commit.
