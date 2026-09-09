# SQAO-LIVE-DERIV v2.4

Sistema de análisis **read-only** para Step Index con datos de mercado de Deriv y una capa multimodal GPT.

## Arquitectura

`Deriv -> OHLC M1/M5/M15/H1/D1 -> SQAO -> snapshot cuantitativo -> GPT Vision + gráficos -> análisis combinado`

El conector usa el WebSocket público actual de Deriv. Para datos públicos de mercado no hace falta API Token.

## Datos en vivo

```bash
source .venv/bin/activate
python -m CONNECTOR.deriv_live
```

El conector descarga 500 velas por defecto en M1/M5/M15/H1/D1, mantiene ticks, construye OHLC, se reconecta automáticamente y actualiza `DATA/live_analysis.json` al completar cada M1.

## Interfaz GPT para subir gráficos

Primero configura la clave de OpenAI **fuera del repositorio**:

```bash
export OPENAI_API_KEY='TU_CLAVE'
export OPENAI_MODEL='gpt-5.6-luna'
```

Después:

```bash
streamlit run AI/app.py --server.address 0.0.0.0 --server.port 8501
```

En el navegador del Codespace abre el puerto 8501. Puedes subir simultáneamente D1, H1, M15, M5 y M1. GPT recibe las imágenes como un conjunto MTF y, si existe, también recibe `DATA/live_analysis.json`.

El resultado se muestra en pantalla y se guarda en `DATA/gpt_analysis.md`.

## Variables Deriv

```text
DERIV_SYMBOL=AUTO
DERIV_STEP_NAME=
SQAO_HISTORY_CANDLES=500
SQAO_DATA_DIR=DATA
```

Si existen varios Step Index y se quiere seleccionar uno concreto, usar `DERIV_STEP_NAME`.

## Seguridad

Esta versión sigue siendo exclusivamente de lectura respecto de Deriv. No implementa `proposal`, `buy` ni `sell`. La clave `OPENAI_API_KEY` no debe guardarse en GitHub ni en archivos versionados; usar una variable de entorno o un Secret del Codespace.

## Interpretación

GPT aporta análisis visual y el motor SQAO aporta análisis cuantitativo. Las probabilidades producidas por el modelo son `MODEL_ESTIMATE`, no win rate histórico. El sistema no garantiza resultados futuros ni rentabilidad.
