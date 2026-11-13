# SQAO Table 18 — Complete numeric ledger V2.1

Run after the canonical OHLC research report is generated:

```bash
python -m ENGINE.table18_full_audit
```

Outputs:
- `DATA/step_index_table18_complete.json`: complete structured table, per-trade ledger, train/OOS summaries, Wilson 95%, net expectancy, net profit factor and net drawdown.
- `DATA/step_index_table18_complete.csv`: spreadsheet-ready row per recorded historical trade.

All entry, stop, target and exit prices are copied from the chronological OHLC backtest. The table does not manufacture TP2/TP3: the baseline strategy tests one target at its configured R multiple. Latest indicator snapshots for D1/H4/H1/M15/M5/M1 are explicitly labelled as report context, not historical-at-entry indicator values. Historical indicator values per trade require recomputation from timestamp-aligned OHLC. Missing fields remain null. Cost configuration is not equivalent to broker verification; eligibility remains NO_TRADE until all required cost and statistical gates pass.

Research-only. No order placement or account credentials.
