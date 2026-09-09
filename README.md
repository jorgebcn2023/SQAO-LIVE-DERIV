# SQAO-LIVE-DERIV v2.5

Sistema de análisis **read-only** para Step Index con datos de mercado de Deriv, motor cuantitativo SQAO y capa multimodal GPT.

## Arquitectura

`Deriv -> OHLC M1/M5/M15/H1/D1 -> SQAO -> snapshot LIVE -> GPT Vision + gráficos -> reconciliación cuant/visual -> LONG/SHORT/WAIT/NO_TRADE`

El conector usa el WebSocket público actual de Deriv. Para datos públicos de mercado no hace falta API Token.

## Datos en vivo

```bash
source .venv/bin/activate
python -m CONNECTOR.deriv_live
```

El conector descarga 500 velas por defecto en M1/M5/M15/H1/D1, mantiene ticks, construye OHLC, se reconecta automáticamente y actualiza `DATA/live_analysis.json` al completar cada M1.

## API LIVE

Render expone el backend read-only. Por defecto la interfaz GPT usa:

`https://sqao-live-api.onrender.com`

Variables opcionales:

```text
SQAO_API_URL=https://sqao-live-api.onrender.com
SQAO_ACTION_KEY=...
```

La interfaz intenta primero `/analysis/snapshot` en vivo. Si no puede acceder, utiliza `DATA/live_analysis.json` local como fallback y lo declara explícitamente en pantalla.

## Interfaz GPT + gráficos

Configura las claves fuera del repositorio:

```bash
export OPENAI_API_KEY='TU_CLAVE'
export OPENAI_MODEL='gpt-5.6'
```

Después:

```bash
streamlit run AI/app.py --server.address 0.0.0.0 --server.port 8501
```

Puedes subir simultáneamente D1, H1, M15, M5 y M1. Se recomienda nombrarlos `D1.png`, `H1.png`, `M15.png`, `M5.png` y `M1.png`, aunque GPT también usa las etiquetas visibles del gráfico.

El flujo ahora:

1. Obtiene el snapshot MTF cuantitativo de Deriv LIVE.
2. Recibe las imágenes MTF.
3. Identifica cada timeframe.
4. Comprueba datos faltantes, duplicados y posibles inconsistencias temporales.
5. Compara dirección cuantitativa frente a estructura visual.
6. Señala desacuerdos entre cuantitativo y visión.
7. Produce una única decisión conservadora: `LONG`, `SHORT`, `WAIT` o `NO_TRADE`.
8. Genera escenarios condicionales a 60 minutos e invalidaciones.

El resultado se muestra en pantalla y se guarda en `DATA/gpt_analysis.md`.

## Seguridad

Esta versión sigue siendo exclusivamente de lectura respecto de Deriv. No implementa `proposal`, `buy` ni `sell`. Las claves `OPENAI_API_KEY` y `SQAO_ACTION_KEY` no deben guardarse en GitHub ni en archivos versionados; usar Secrets/variables de entorno.

## Interpretación

GPT aporta análisis visual y el motor SQAO aporta datos cuantitativos. Las probabilidades producidas por el modelo son `MODEL_ESTIMATE`, no win rate histórico. El sistema no garantiza resultados futuros ni rentabilidad. Si las fuentes no están sincronizadas o faltan datos, el sistema debe reducir confianza y favorecer `WAIT`/`NO_TRADE`.
