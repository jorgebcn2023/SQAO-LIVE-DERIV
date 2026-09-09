# SQAO-LIVE-DERIV v2.3

Sistema de análisis **read-only** para Step Index con datos de mercado de Deriv.

## Flujo

`Deriv active_symbols -> histórico M1/M5/M15/H1/D1 -> ticks en vivo -> OHLC -> motor predictivo SQAO`

El conector usa el WebSocket público de Deriv por defecto, por lo que **no necesita API Token para datos de mercado**. La API pública expone `active_symbols`, `ticks` y `ticks_history` sin autenticación. citehttps://developers.deriv.com/docs/options/ws-public/

## Ejecutar en Codespaces

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r ENGINE/requirements.txt
python -m ENGINE.tests
```

Después, en una terminal:

```bash
python -m CONNECTOR.deriv_live
```

Y en otra:

```bash
python -m ENGINE.live_pipeline
```

## Configuración

Por defecto:

```text
DERIV_SYMBOL=AUTO
DERIV_AUTH_MODE=public
SQAO_HISTORY_CANDLES=500
SQAO_DATA_DIR=DATA
```

Para varios Step Index, se puede establecer `DERIV_STEP_NAME` para seleccionar por nombre.

## Seguridad

Esta versión no implementa `proposal`, `buy`, `sell` ni ninguna operación de trading. No guardar el PAT/API Token en el repositorio. Si en el futuro se usa autenticación, utilizar variables de entorno o Codespaces Secrets.

## Validación

Las puntuaciones del motor son `MODEL_ESTIMATE` hasta disponer de un backtest válido. Nunca se presentan como win rate histórico.
