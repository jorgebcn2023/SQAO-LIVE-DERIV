# SQAO-LIVE-DERIV v3.2.1

Sistema de análisis **read-only** para Synthetic Indices de Deriv, con motor cuantitativo SQAO, análisis MTF y capa multimodal GPT.

## Arquitectura

`Deriv public WS -> Synthetic Discovery -> historical research -> MTF analysis D1/H1/M15/M5/M1 -> risk-adjusted ranking -> GPT Vision -> conservative decision`

El backend usa el WebSocket público de Deriv para datos de mercado sin autenticación.

## Componentes principales

- `CONNECTOR/deriv_live.py`: conexión persistente de ticks/OHLC y snapshot local.
- `ENGINE/live_pipeline.py`: EMA10/EMA20, RSI14, ATR14, rangos, alineación MTF y decisión conservadora.
- `ENGINE/synthetic_scanner.py`: clasificación de familias Synthetic y `SAFETY/MODELABILITY/MTF/SETUP/COMPOSITE` scores.
- `ENGINE/synthetic_research.py`: descubrimiento dinámico, históricos M5, backtest reproducible, expectancy, profit factor, drawdown, Sharpe, Sortino y walk-forward.
- `ENGINE/predictive.py`: escenarios condicionales como `MODEL_ESTIMATE`.
- `API/app.py`: API FastAPI read-only en Render.
- `AI/app.py`: interfaz Streamlit.
- `AI/gpt_vision.py`: reconciliación cuantitativo/visual.
- `GPT/openapi.yaml`: especificación para integrar el backend con GPT.
- `.github/workflows/test.yml`: CI del motor y smoke test Deriv.
- `.github/workflows/synthetic-research.yml`: investigación programada cada 6 horas y publicación del ranking como artifact.

## Research Engine

El ranking histórico no asume que un índice sea siempre rentable. Para cada Synthetic Index descubierto se calcula una estrategia reproducible basada en EMA10/EMA20, ruptura de 20 velas y ATR14, y se evalúa con:

- Win rate
- Expectancy en R
- Profit factor
- Max drawdown
- Sharpe
- Sortino
- Walk-forward expectancy
- Score ajustado por riesgo

Los resultados son **diagnóstico histórico** y no constituyen una predicción ni garantía de rentabilidad futura.

## GitHub Actions

El workflow `SQAO Synthetic Research` se ejecuta:

- automáticamente cada 6 horas;
- manualmente mediante `workflow_dispatch`;
- cuando cambian los componentes del research engine en `main`.

El resultado se guarda como artifact `sqao-synthetic-research-*` durante 14 días.

## API LIVE

Backend Render:

`https://sqao-live-api.onrender.com`

Endpoints principales:

- `/health`
- `/market/active-symbols`
- `/market/ohlc?symbol=AUTO&timeframe=M1&count=120`
- `/analysis/snapshot?symbol=AUTO&count=120`

## Seguridad

No hay operaciones de trading: no se implementan `proposal`, `buy` ni `sell`. Las claves OpenAI/SQAO deben permanecer fuera de GitHub. El research engine utiliza únicamente datos públicos de mercado.

## Validación

```bash
bash RUN-CODESPACE.sh
python -m compileall -q API AI ENGINE CONNECTOR
python -m ENGINE.tests
python -m ENGINE.synthetic_research
```


## Step Index Quant Validation (added)

Research-only statistical tooling for Step Index is available in `ENGINE/step_index_quant.py`. It adds:

- Natural-logarithmic market returns: `ln(P[t] / P[t-1])`.
- R-multiple equity statistics: observed win rate, two-sided Wilson 95% confidence interval, expectancy, sample deviation, profit factor, drawdown, per-trade Sharpe/Sortino.
- Hypothetical risk-fraction compounding at 0.5%, 1%, and 2%, using log growth `sum(ln(1 + f * R))`.
- An explicit evidence gate requiring at least 100 out-of-sample trades, observed win rate at/above target, Wilson lower 95% bound at/above target, positive net expectancy, profit factor above 1, and user-supplied round-trip costs.
- Regression tests in `ENGINE/test_step_index_quant.py`.

Example validation command:

```bash
python -m ENGINE.test_step_index_quant
```

**Important:** the 70% figure is an acceptance threshold, never a guaranteed result or the probability of the next trade. This helper analyzes supplied closed-trade R multiples and close prices; it does not by itself perform a live Step Index backtest. Use clean chronological out-of-sample OHLC data and realistic spread/commission/slippage inputs before evaluating any strategy. If the evidence gate fails, the correct output is `NO_TRADE`.


## Step Index research pipeline (end-to-end)

Run a Step Index-specific, read-only historical analysis and generate a reproducible executive PDF plus JSON:

```bash
python -m ENGINE.step_index_research
```

The pipeline discovers the actual active Step Index symbol from Deriv's public API (does not silently substitute another instrument), retrieves closed candles in paginated blocks, and reports M1/M5/M15/H1/D1/W1 indicators: EMA10/20, RSI14, ATR14, MACD(12,26,9), Bollinger(20,2), stochastic and rolling-range Fibonacci levels. Fibonacci values are range estimates, not confirmed pivot levels.

The baseline research rule is fixed before evaluation: M5 close breakout of the prior 20-candle high/low plus EMA10/20 direction, filtered by matching EMA10/20 direction on already-closed M15 and H1 candles. The simulated entry is the next M5 open, stop distance is 1.2 ATR, target is 1.5R, horizon is five M5 bars, and ambiguous same-bar stop/target events count as stop-first. It uses a chronological 70/30 train/holdout split and includes subperiod breakdowns, log-return distribution, confidence intervals, drawdown, expectancy, profit factor and a hypothetical equity curve.

Outputs:
- `DATA/step_index_quant_report.pdf`
- `DATA/step_index_quant_report.json`

GitHub Actions workflow `.github/workflows/step-index-quant.yml` runs every six hours, supports manual dispatch, and uploads both outputs as a 30-day artifact. Configure repository Actions variable `SQAO_STEP_ROUND_TRIP_COST_PRICE` with a realistic total round-trip cost in quote-price units. Without that value, cost-adjusted eligibility is intentionally blocked and the result remains `NO_TRADE`.

This baseline does not claim a 70% future hit rate. The statistical gate needs at least 100 OOS trades, observed win rate >=70%, Wilson 95% lower bound >=70%, positive net expectancy, profit factor >1 and declared transaction costs. Passing the gate only makes a candidate eligible for further review; it does not guarantee the next trade and does not by itself authorize execution. No order-placement API is used.


## SQAO V2.1 — Screenshot Visual Extraction

The chart-vision layer now calls `ENGINE/chart_visual_extraction.py` for every uploaded image before GPT Vision reconciliation. It records the detected timeframe, OCR text and numeric tokens with image coordinates, visible MACD readouts, right-axis price labels, a best-effort axis calibration, and a possible horizontal quote-line estimate. Values retain their screenshot provenance and are never silently promoted to OHLC or executable quotes.

The complete Table 18 LONG/SHORT numeric schema is emitted by `table18_template()`. Unsupported fields remain JSON `null` (not zero); this preserves all columns without inventing EMA/RSI/ATR/ADX/Stochastic values, entry, SL, TP, OOS metrics, or transaction costs. Screenshot extraction is complementary to, not a replacement for, timestamped closed OHLC, synchronized MTF data, cost verification, and chronological OOS/walk-forward validation.

Optional OCR runtime: Python packages in `ENGINE/requirements.txt` plus the Tesseract OCR system binary. CI installs Tesseract and runs `python -m ENGINE.test_chart_visual_extraction`. If OCR is unavailable, the engine reports the dependency/runtime failure and fails closed. The system remains READ-ONLY / RESEARCH-ONLY; no order endpoints are introduced.

To call from Python:

```python
from ENGINE.chart_visual_extraction import build_visual_audit
report = build_visual_audit({
    "H4": "charts/step_h4.png",
    "H1": "charts/step_h1.png",
    "M15": "charts/step_m15.png",
    "M5": "charts/step_m5.png",
    "M1": "charts/step_m1.png",
}, output="DATA/chart_visual_audit.json")
```


## SQAO V2.2 — Research reliability and checkpoints

The Step Index quant workflow has bounded stage timeouts and separate diagnostic checkpoints. The baseline research job timeout is 90 minutes (70 minutes for OHLC research); Table 18 is audited as a separate stage. Baseline JSON/PDF and Table 18 JSON/CSV are uploaded independently even when a later stage fails. The consolidated report artifact is published only after all validations pass.

Checkpoint artifacts preserve completed outputs for inspection and manual recovery. GitHub Actions reruns still restart from the beginning; automatic resume from a previous run's artifacts is not implemented. See `docs/SQAO_V22_RESEARCH_RELIABILITY.md`.

The change does not relax the statistical acceptance gate or safety rules. Missing verified all-in costs or insufficient OOS evidence continue to produce `NO_TRADE`.


## SQAO V2.3 — Research performance optimization

The baseline Step Index backtest now avoids recalculating full-history MTF indicator snapshots for every trade. The complete MTF indicator audit remains available at report level. Repeated per-trade snapshots are opt-in with `SQAO_INCLUDE_TRADE_INDICATOR_SNAPSHOTS=1`; the default is off to reduce avoidable work on large OHLC histories. The report records this setting under `diagnostics.per_trade_indicator_snapshots_enabled`. This is a performance/diagnostic change only; it does not change the strategy, market data, costs, or acceptance gate. See `docs/SQAO_V23_RESEARCH_PERFORMANCE.md`.


## SQAO V2.4 — Quant workflow queue isolation

V2.4 scopes the Step Index quantitative workflow concurrency group to the Git ref. A long-running research job on another branch can no longer hold the global queue and leave the current PR validation pending. Runs on the same ref remain serialized; no research or trading logic is changed. See [`docs/SQAO_V24_QUANT_QUEUE_ISOLATION.md`](docs/SQAO_V24_QUANT_QUEUE_ISOLATION.md).
