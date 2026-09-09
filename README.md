# SQAO-LIVE-DERIV v2.6

Sistema de análisis **read-only** para Step Index con datos públicos de mercado de Deriv, motor cuantitativo SQAO y capa multimodal GPT.

## Arquitectura

`Deriv public WS -> Step Index AUTO -> D1/H1/M15/M5/M1 -> indicadores cuantitativos -> decisión conservadora -> GPT Vision + gráficos -> reconciliación cuant/visual`

El backend usa el WebSocket público actual de Deriv para datos de mercado sin autenticación.

## Componentes

- `CONNECTOR/deriv_live.py`: conexión persistente de ticks, OHLC M1/M5/M15/H1/D1, reconexión y snapshot local.
- `ENGINE/live_pipeline.py`: EMA10/EMA20, RSI14, ATR14, rangos, alineación MTF y decisión conservadora.
- `ENGINE/predictive.py`: escenarios condicionales de 60 minutos como `MODEL_ESTIMATE`.
- `API/app.py`: API FastAPI read-only en Render; autodetecta el Step Index cuando `symbol=AUTO`.
- `AI/app.py`: interfaz Streamlit para datos LIVE y carga de gráficos.
- `AI/gpt_vision.py`: reconciliación entre cuantitativo y visión.
- `GPT/openapi.yaml`: especificación para integrar el backend como Action/API de GPT.

## Decisiones

El motor solo devuelve `LONG`, `SHORT`, `WAIT` o `NO_TRADE`. En modo conservador, una entrada direccional requiere alineación MTF completa y confirmación en M5; en caso contrario favorece `WAIT`/`NO_TRADE`.

Las probabilidades y escenarios son `MODEL_ESTIMATE`. No son win rate histórico y no implican rentabilidad garantizada.

## API LIVE

Backend Render:

`https://sqao-live-api.onrender.com`

Endpoints principales:

- `/health`
- `/market/active-symbols`
- `/market/ohlc?symbol=AUTO&timeframe=M1&count=120`
- `/analysis/snapshot?symbol=AUTO&count=120`

Variables opcionales:

```text
SQAO_API_URL=https://sqao-live-api.onrender.com
SQAO_ACTION_KEY=...
DERIV_SYMBOL=AUTO
DERIV_STEP_NAME=...
SQAO_HISTORY_CANDLES=500
```

## Streamlit

```bash
source .venv/bin/activate
streamlit run AI/app.py --server.address 0.0.0.0 --server.port 8501
```

La interfaz permite introducir la URL de API, clave SQAO opcional, clave OpenAI de sesión, modelo y símbolo. `AUTO` autodetecta el Step Index activo.

Sube `D1`, `H1`, `M15`, `M5` y `M1`. El sistema:

1. Obtiene datos LIVE de Deriv.
2. Calcula el snapshot cuantitativo.
3. Comprueba completitud y alineación MTF.
4. Recibe los cinco gráficos.
5. Compara cuantitativo vs. visión.
6. Detecta inconsistencias temporales.
7. Produce una decisión única y escenarios de 60 minutos.

Si Deriv LIVE no está disponible, el sistema lo marca y puede usar `DATA/live_analysis.json` como fallback local; nunca debe presentarlo como LIVE.

## Seguridad

No hay operaciones de trading: no se implementan `proposal`, `buy` ni `sell`. Las claves OpenAI/SQAO deben permanecer fuera de GitHub. La API pública de Deriv usada aquí no requiere token para datos de mercado.

## Validación

```bash
bash RUN-CODESPACE.sh
```

El script compila el código y ejecuta las pruebas del motor antes de iniciar cualquier proceso LIVE.
