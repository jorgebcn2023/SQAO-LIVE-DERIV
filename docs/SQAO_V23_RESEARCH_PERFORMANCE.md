# SQAO V2.3 — Research performance patch

## Purpose

Reduce avoidable repeated indicator work in the long Step Index OHLC backtest. The preceding run showed that the workflow could pass compilation, MT5 evidence audit, the V23 detector and its chronological backtest, then remain for a long time in the baseline OHLC research stage.

## Change

The backtest previously recalculated full-prefix MTF indicator snapshots for every simulated trade. With large histories, that repeated work grows with both history length and number of trades.

V2.3 keeps the complete MTF indicator audit at report level, but makes the redundant per-trade copies opt-in:

- Default: `SQAO_INCLUDE_TRADE_INDICATOR_SNAPSHOTS=0`; per-trade field remains present as an empty object.
- Diagnostic mode: set `SQAO_INCLUDE_TRADE_INDICATOR_SNAPSHOTS=1` to retain the verbose per-trade snapshots.
- The report records the setting under `diagnostics.per_trade_indicator_snapshots_enabled`.

This changes diagnostic verbosity, not the trading rule, OHLC data, signal timestamps, entry/SL/TP simulation, costs, sample split, or statistical acceptance gate.

## Safety and evidence

- Read-only / research-only; no order endpoints.
- Quantitative calculations continue to use closed, timestamped OHLC.
- Report-level MTF indicators remain available.
- Missing costs or insufficient out-of-sample evidence still produce `NO_TRADE`.
- This optimization is not proof of a successful run. CI must complete the research stage and publish the baseline and Table 18 checkpoints before V2.3 can be considered validated.

## Validation

Run the normal test suite and `python -m ENGINE.step_index_research`. Compare output metadata and the baseline checkpoint. If full per-trade traceability is needed for a diagnostic run, enable the environment variable above.
