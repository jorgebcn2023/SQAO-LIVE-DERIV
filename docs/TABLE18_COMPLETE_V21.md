# SQAO Table 18 — Complete numeric ledger V2.1

Run after the canonical OHLC research report is generated:

```bash
python -m ENGINE.table18_full_audit
```

Outputs:
- `DATA/step_index_table18_complete.json`: complete structured table, per-trade ledger, train/OOS summaries, Wilson 95%, net expectancy, net profit factor and net drawdown.
- `DATA/step_index_table18_complete.csv`: spreadsheet-ready row per recorded historical trade.

All entry, stop, target and exit prices are copied from the chronological OHLC backtest. The table does not manufacture TP2/TP3: the baseline strategy tests one target at its configured R multiple. For each historical trade, EMA9/20/50, Bollinger20/2, MACD12/26/9, Wilder RSI/ATR/ADX/DI14 and Stochastic14/3/3 are recomputed from D1/H4/H1/M15/M5/M1 candles closed by that trade's signal timestamp and stored with the row. Missing fields remain null. Cost configuration is not equivalent to broker verification; eligibility remains NO_TRADE until all required cost and statistical gates pass.

Research-only. No order placement or account credentials.
