# Conectar SQAO con ChatGPT (Custom GPT)

Este procedimiento conecta un GPT personalizado con la API de mercado del repositorio. **Subir el ZIP a un chat normal no ejecuta el código ni habilita llamadas a la API automáticamente.**

## 1. Confirmar la API

Abrir:
- Salud: https://sqao-live-api.onrender.com/health
- OpenAPI de FastAPI: https://sqao-live-api.onrender.com/openapi.json
- Snapshot MTF: https://sqao-live-api.onrender.com/analysis/snapshot?symbol=AUTO&count=120

En /health, revisar `status`, `version`, `background_connector_enabled` y `background_connector_running`. El último campo indica que la tarea está activa, no certifica por sí solo que hayan llegado ticks recientes. Confirmar el snapshot y que las velas incluyan D1/H1/M15/M5/M1.

## 2. Crear o editar un GPT

1. Abrir el editor de GPTs de ChatGPT en la web y crear un GPT o editar el existente. La creación/edición de GPTs puede no estar disponible en la aplicación móvil.
2. En **Instructions**, pegar el contenido de `GPT/SQAO_GPT_INSTRUCTIONS.md`.
3. En **Actions**, elegir crear/importar una acción y pegar el esquema OpenAPI de `GPT/openapi.yaml`.
4. Confirmar que el servidor del esquema sea `https://sqao-live-api.onrender.com`.
5. Si la API está configurada con `SQAO_ACTION_KEY`, configurar la autenticación de la acción con esa misma clave en el header `X-SQAO-Key`. No incluir la clave en instrucciones, archivos públicos, capturas ni commits. Si no se ha configurado una clave en Render, los endpoints de lectura son públicos.
6. Guardar y probar `health`, `getActiveStepSymbols` y `getSQAOQuantSnapshot`.

Esquema fuente para copiar:
https://raw.githubusercontent.com/jorgebcn2023/SQAO-LIVE-DERIV/main/GPT/openapi.yaml

Instrucciones fuente:
https://raw.githubusercontent.com/jorgebcn2023/SQAO-LIVE-DERIV/main/GPT/SQAO_GPT_INSTRUCTIONS.md

## 3. Usarlo en el chat

- Para un análisis en vivo: pedir explícitamente “Consulta la API SQAO y analiza Step Index con D1/H1/M15/M5/M1”.
- Para un análisis visual: adjuntar las capturas y pedir que se contrasten con el snapshot de la API.
- Si la acción falla, el GPT debe declararlo y no simular datos en vivo.
- Los resultados de escenarios son estimaciones, no probabilidades de éxito validadas. No existe una garantía de efectividad superior al 70 %.

## Limitaciones

- El ZIP es el paquete de código/instrucciones; un GPT personalizado debe tener configurada su Action para llamar a la API.
- La API actual es de solo lectura; no ejecuta órdenes de trading.
- Un servicio gratuito de alojamiento puede suspenderse o reiniciarse. No asumir captura continua 24/7 sin monitorizar disponibilidad y frescura de datos.
