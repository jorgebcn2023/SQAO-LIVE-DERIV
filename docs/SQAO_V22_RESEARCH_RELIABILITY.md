# SQAO V2.2 — Research pipeline reliability

## Purpose

V2.2 hardens the Step Index research workflow after the previous 35-minute job was cancelled during the OHLC research stage. It does not change the trading rule, indicators, entry/SL/TP calculations, or acceptance thresholds.

## Changes

- Raises the research job timeout from 35 to 90 minutes.
- Gives the long OHLC research stage a 70-minute step timeout.
- Prevents a newly queued run from automatically cancelling an active run in the same concurrency group.
- Separates the Table 18 audit from baseline OHLC research.
- Uploads baseline JSON/PDF and Table 18 JSON/CSV as independent diagnostic checkpoints with `if: always()`.
- Gives the strategy laboratory and ARIMA/Monte Carlo bounded 30-minute step timeouts.
- Publishes the consolidated reproducibility artifact only after all stages and validations succeed.

## Recovery behavior and limitations

The checkpoint artifacts preserve completed outputs when a later stage fails or is cancelled. They can be downloaded and inspected independently. GitHub Actions reruns still restart the workflow from its first step; this version does **not** claim automatic in-place resume from a previous run's artifact. A later stage can be rerun locally after downloading its required checkpoint, subject to its input contract.

## Acceptance and safety

- Research-only / read-only. No order placement endpoints.
- Only fully closed, timestamped Deriv OHLC candles are used for quantitative calculations.
- Screenshot OCR is supplemental and is never converted into OHLC.
- Missing or unverified values remain null/unknown.
- Missing verifiable all-in costs block net performance claims.
- The acceptance gate remains unchanged: at least 100 OOS trades, target win rate and Wilson lower bound, positive net expectancy, profit factor above one, and configured costs.
- Any unmet evidence gate remains `NO_TRADE`.

## Previous run diagnosis

Run 43507701332 attempt 2 completed with conclusion `cancelled`. The baseline research command was interrupted after approximately 32 minutes in that step. The earlier stages passed, but the strategy lab, 10,000-path Monte Carlo, output validation, and consolidated artifact upload were skipped. No final PDF/JSON artifact was published by that run.

## Verification

After merging this branch, manually dispatch `SQAO Step Index Quant Research` or let the PR workflow run. Confirm that the baseline checkpoint, Table 18 checkpoint, and final artifact appear separately. A green compile/test stage alone is not evidence that the research report or strategy is eligible for trading.
