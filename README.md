# SQAO-LIVE-DERIV v2.3

Sistema de análisis **read-only** para Step Index con datos de mercado de Deriv.

## Qué hace

`Deriv active_symbols -> histórico M1/M5/M15/H1/D1 -> ticks en vivo -> OHLC -> análisis SQAO -> DATA/live_analysis.json`

El conector usa el WebSocket público actual de Deriv. Para datos públicos de mercado **no hace falta API Token**.

## Codespaces

El repositorio incluye configuración de Dev Container. Al crear/reconstruir un Codespace se ejecuta automáticamente `RUN-CODESPACE.sh`, que:

1. crea `.venv`;
2. instala dependencias;
3. compila `ENGINE` y `CONNECTOR` para detectar errores de sintaxis;
4. ejecuta las pruebas;
5. valida el pipeline.

Si el Codespace ya existía, ejecutar una vez:

```bash
bash RUN-CODESPACE.sh
```

## Arranque en vivo

```bash
source .venv/bin/activate
python -m CONNECTOR.deriv_live
```

El conector:

- autodetecta el Step Index;
- descarga 500 velas por defecto en M1/M5/M15/H1/D1;
- mantiene ticks en `DATA/ticks.ndjson`;
- construye OHLC en vivo;
- se reconecta automáticamente si se corta el WebSocket;
- actualiza `DATA/live_analysis.json` al completar cada vela M1.

## Configuración

Variables disponibles:

```text
DERIV_SYMBOL=AUTO
DERIV_STEP_NAME=
SQAO_HISTORY_CANDLES=500
SQAO_DATA_DIR=DATA
```

Si existen varios Step Index y se quiere seleccionar uno concreto, usar `DERIV_STEP_NAME`.

## Seguridad

Esta versión es exclusivamente de lectura. No implementa `proposal`, `buy`, `sell` ni otras operaciones de trading. No guardar PAT/API Tokens en el repositorio público. Para autenticación futura, usar variables de entorno o Codespaces Secrets.

## Estado del análisis

Las puntuaciones del motor son `MODEL_ESTIMATE` hasta disponer de un backtest válido. No se presentan como win rate histórico.
