# SQAO Complete OS — paquete GitHub

Este repositorio es la fuente de verdad del sistema. El ZIP completo se construye desde el commit probado por GitHub Actions; no incluye credenciales, archivos `.env`, ni datos locales de ejecución.

## Qué contiene
- Motor de análisis multitemporal y conectores públicos de Deriv.
- Pipeline cuantitativo Step Index con indicadores, backtest cronológico y generación PDF/JSON.
- Laboratorio de comparación predefinida de tres reglas: ruptura de 20 velas con filtros MTF, pullback EMA y reversión RSI.
- Pruebas, API, interfaz AI, definición OpenAPI y documentación para GPT.
- Workflows de CI, investigación y empaquetado ZIP.

## Ejecutar desde GitHub
1. Abre Actions en el repositorio y ejecuta **SQAO Complete OS Package** con **Run workflow**.
2. Espera a que finalicen los tests.
3. Descarga el artifact `sqao-live-deriv-complete-os`; contiene `SQAO_LIVE_DERIV_COMPLETE_OS_GITHUB.zip`.
4. Para investigación, ejecuta **SQAO Step Index Quant Research**. Genera PDF/JSON baseline.
5. Ejecuta el módulo `python -m ENGINE.step_index_strategy_lab` para comparar las reglas alternativas.

## Ejecutar localmente
Python 3.12:
```bash
python -m pip install -r ENGINE/requirements.txt -r API/requirements.txt
python -m compileall -q API AI ENGINE CONNECTOR
python -m ENGINE.tests
python -m ENGINE.test_step_index_quant
python -m ENGINE.test_step_index_strategy_lab
python -m ENGINE.step_index_research
python -m ENGINE.step_index_strategy_lab
```

Configura la variable Actions `SQAO_STEP_ROUND_TRIP_COST_PRICE` con el coste total real de ida y vuelta en unidades de precio cotizado. Sin costes realistas el filtro de elegibilidad no pasa.

## Control estadístico
El 70 % es un umbral de validación, no una promesa. Cada candidato debe tener al menos 100 operaciones OOS, win rate observado e inferior Wilson 95 % por encima del umbral, expectativa neta positiva, profit factor > 1 y costes definidos. Los parámetros son fijos y el resultado no es una probabilidad de la próxima operación. Si falla cualquier requisito, el resultado es `NO_TRADE`.

## Seguridad
Solo investigación y análisis. No se implementa ejecución de órdenes. Nunca guardes tokens, contraseñas o claves en el repositorio.
