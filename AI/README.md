# GPT Vision + Live Quant

La interfaz combina los gráficos MTF subidos por el usuario con el snapshot cuantitativo LIVE de SQAO.

## Uso

```bash
source .venv/bin/activate
streamlit run AI/app.py --server.address 0.0.0.0 --server.port 8501
```

En la barra lateral puedes configurar:

- URL del backend SQAO.
- `SQAO_ACTION_KEY` si el backend está protegido.
- OpenAI API key de sesión.
- Modelo OpenAI.
- Step Index (`AUTO` autodetecta el símbolo activo).
- Número de velas por timeframe.

Después sube D1/H1/M15/M5/M1 y pulsa **Analizar con SQAO + GPT**.

La interfaz no guarda la OpenAI API key en GitHub. El resultado se guarda localmente en `DATA/gpt_analysis.md`.

La capa GPT debe distinguir datos observados, inferencias y escenarios `MODEL_ESTIMATE`; nunca debe presentar una estimación como win rate histórico ni como garantía.