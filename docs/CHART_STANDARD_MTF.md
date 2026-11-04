# SQAO — Estándar gráfico oficial MTF

**Estado:** obligatorio para todos los análisis de Step Index, snapshots y reportes PDF.
**Modo:** read-only / research-only.
**Objetivo:** uniformar la lectura visual y cuantitativa, no crear señales por acumulación de indicadores.

## 1. Marcos temporales

| Marco | Función |
|---|---|
| H4 | Contexto direccional amplio |
| H1 | Contexto operativo |
| M15 | Estructura, zonas y alineación |
| M5 | Setup de scalping |
| M1 | Timing y trigger con vela cerrada |

D1 puede añadirse como contexto macro cuando el histórico sea suficiente. No sustituye H4/H1.

## 2. Diseño de cada gráfico

- **Panel principal:** velas japonesas OHLC, EMA 9 (rápida), EMA 20 (intermedia), EMA 50 (tendencia), Bollinger (20, desviación 2).
- **Panel MACD:** MACD (12,26,9), línea, señal e histograma.
- **Panel RSI:** RSI (14), referencias 30/50/70. Son referencias descriptivas, no disparadores automáticos.
- **Panel volatilidad:** ATR (14), en unidades de precio.
- **Panel fuerza direccional:** ADX (14), +DI y -DI.
- Estocástico (9,3,3) opcional para diagnóstico; no contarlo como confirmación independiente adicional al RSI.

Cada panel debe identificar símbolo, timeframe, zona horaria, hora de cierre de la última vela, parámetros y fuente de datos. Mantener colores, escalas y orden de paneles constantes entre temporalidades.

## 3. Reglas de cálculo y evidencia

1. Calcular indicadores exclusivamente con OHLC de Deriv con timestamp; excluir velas abiertas, duplicadas, corruptas y datos no alineados.
2. No derivar OHLC exactos ni valores de indicadores desde píxeles de capturas. La imagen sirve para lectura visual auxiliar; si hay discrepancia, prevalecen los datos OHLC.
3. No usar información futura: cada marco superior debe estar cerrado en el instante de decisión del marco inferior.
4. Mostrar valores no disponibles como **NO DISPONIBLE**, nunca estimarlos silenciosamente.
5. Informar por marco: sesgo EMA, relación precio/Bollinger, MACD, RSI, ATR y ADX/DI. Separar hechos calculados, interpretación y limitaciones.
6. Los indicadores son transformaciones del precio y pueden ser redundantes. No sumar votos como si fueran evidencias independientes ni inferir probabilidad a partir de confluencia visual.
7. No cambiar reglas de entrada, parámetros de backtest ni criterios estadísticos por adoptar este formato. Cualquier cambio de estrategia requiere versión, hipótesis, backtest cronológico y OOS independiente.

## 4. Requisitos de los informes

Todo informe PDF completo debe incluir cinco gráficos homogéneos M1, M5, M15, H1 y H4 con los paneles definidos; tabla MTF con último cierre, EMA 9/20/50, Bollinger, MACD, RSI, ATR, ADX/+DI/-DI y sesgo; interpretación de contexto H4/H1, estructura M15, setup M5 y trigger M1; símbolo, hora UTC y cantidad de velas válidas.

Si falta un marco o indicador, marcarlo como NO DISPONIBLE y explicar la limitación. En resúmenes cortos, incluir al menos la tabla MTF y declarar qué gráficos no se han generado.

## 5. Compuertas operativas

Este estándar es exclusivamente de presentación y análisis. No relaja ni reemplaza la validación OOS cronológica, muestra suficiente, costes completos de ida y vuelta verificados, expectativa neta positiva, PF superior a 1, intervalo Wilson y trigger actual confirmado con datos cerrados.

Si falla cualquier requisito, la salida es **NO_TRADE**. Nunca inventar entrada, SL, TP, lotaje, porcentaje de efectividad ni datos. No ejecutar órdenes.