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
