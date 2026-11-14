# SQAO LIVE DERIV V2.4.5 — Release notes

Date: 2026-11-14

## Integrated repository change

This release aligns the ChatGPT plugin instructions with PR #23, merged into
`fix/v23-backtest-early-exit-oos-100k`.

Merge commit: `1877cc51c83bdab3aa6bd1c50578075da61da373`

The shared resolver in `ENGINE/deriv_symbols.py`:
- Requires an exact unique match when `DERIV_STEP_NAME` is supplied.
- Auto-selects only when exactly one Step Index candidate is discovered.
- Fails closed with `STEP_INDEX_SYMBOL_NOT_FOUND`,
  `AMBIGUOUS_STEP_INDEX_SYMBOL`, or
  `STEP_INDEX_SYMBOL_SELECTION_FAILED`.
- Prevents silent fallback to `stpRNG` or selection of the first candidate.
- Stops OHLC retrieval, backtesting and signal generation when identity is ambiguous.

## CI status

The PR validation CI passed, including resolver regression tests and the public
Deriv WebSocket smoke test. This does not prove that the complete quantitative
research workflow has run or that 100,000 M1 candles have been retrieved.

## Research gate

Keep the system READ-ONLY / RESEARCH-ONLY and default to `NO_TRADE`.
Before any trade research can be accepted, verify the exact symbol, timestamped
closed OHLC, historical feature causality, round-trip costs, chronological
walk-forward/OOS metrics, leakage tests and reproducible artifacts.

The previous reference audit had negative gross OOS expectancy
(-0.0448 R) and gross OOS profit factor 0.9066; costs were unverified.
Do not claim a validated edge from CI success.
