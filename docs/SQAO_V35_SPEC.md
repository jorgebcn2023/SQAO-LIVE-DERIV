# SQAO LIVE DERIV V3.5 — Technical Specification

Status: experimental implementation baseline. READ-ONLY / RESEARCH-ONLY.

## Version isolation
V3.5 is developed on branch `sqao-v3.5`. The `main` branch and existing V3.0/V2.x artifacts remain unchanged. No deployment or trading execution is part of this change.

## Existing repository baseline
The project already contains closed-candle filtering, MTF synchronization, quant metrics, chronological backtesting, cost audits and a Deriv public-data connector. V3.5 adds a separately namespaced pure research engine rather than replacing those paths.

## Modules
- Statistical: log returns, sample autocorrelation and median-based runs test.
- Data quality: OHLC validation, closed-candle exclusion, duplicate and gap reporting.
- Indicators: EMA, RSI and MACD with minimum-sample guards.
- Regime: EMA20/EMA50 separation classifier (experimental threshold).
- MTF: initial weights D1 35%, H4 25%, H1 15%, M15 15%, M5 5%, M1 5%. Scores are confluence weights, never probabilities.
- Risk: tick-size/tick-value sizing, volume-step flooring, minimum-volume rejection and optional estimated per-lot costs.
- Decision: fail-closed NO_TRADE if any data, MTF, cost, OOS, technical or risk gate fails.

## Statistical caveats
The runs test and ACF are diagnostics, not proof of predictive alpha. A production Ljung–Box p-value, ADX/DI, ATR-normalized regime model, BOS/CHoCH/OB/FVG detectors and walk-forward optimizer remain future tasks. No SMC/AMD manipulation narrative is treated as fact. No 65% win rate or 70% result is assumed.

## Data contract
OHLC input rows use `epoch, open, high, low, close`. The caller supplies timeframe seconds and a UTC epoch for closed-candle validation. All values remain quoted price units until separately verified MT5 symbol metadata is supplied.

## Risk contract
`size_position` requires verified tick size, tick value, volume minimum and step. If the minimum legal volume risks more than the budget, the output is NO_TRADE. A cost estimate may be supplied per lot; unknown costs must fail the external cost gate.

## Execution safety
The engine has no network, broker, MetaTrader or order-placement imports. Every decision response sets `execution_eligible=false`. The system is analytical only.

## Validation
Run:
```bash
python -m pytest ENGINE/test_sqao_v35_engine.py
```
These tests validate code behavior only; they do not demonstrate trading profitability.
