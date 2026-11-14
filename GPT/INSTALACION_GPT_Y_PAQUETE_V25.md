# SQAO LIVE DERIV V2.5 — Instalación del GPT y del paquete completo

## A. GPT personalizado con Action

### 1. Crear el GPT
En ChatGPT abre Explorar GPTs -> Crear. En Configurar:
- Nombre: SQAO LIVE DERIV V2.5
- Descripción: Analista cuantitativo read-only para Deriv Step Index con OCR visual, OHLC real y sincronización MTF.
- Instrucciones: pega el contenido completo de `GPT/SQAO_GPT_INSTRUCTIONS.md`.
- Acciones: selecciona Crear nueva acción e importa `GPT/openapi.yaml`.
- Autenticación: Ninguna, porque la API documentada usa datos públicos y endpoints read-only.
- Guarda como privado mientras verificas su funcionamiento.

### 2. Validar la Action
Prueba estas operaciones desde el panel de acciones:
1. `health`: debe responder y mostrar versión/estado/frescura.
2. `getActiveStepSymbols`: debe devolver el símbolo real activo.
3. `getSQAOQuantSnapshot`: debe devolver las seis temporalidades D1/H4/H1/M15/M5/M1 con timestamps y auditoría de sincronización.
4. `getStepOHLC`: prueba M1 con count=120.

Si la API devuelve error, datos incompletos o timestamps no sincronizados, el GPT debe responder WAIT/NO_TRADE. No inventes una URL alternativa ni declares que Render está activo sin respuesta HTTP satisfactoria.

### 3. Configuración de publicación
Mantén el GPT privado durante las pruebas. La publicación/compartición es una decisión manual del propietario. No añadas credenciales de Deriv: esta integración no las necesita.

## B. Paquete ZIP completo

El paquete instalable se genera mediante GitHub Actions:
- Workflow: `.github/workflows/sqao-complete-os-package.yml`
- Artifact: `sqao-live-deriv-complete-os`
- ZIP: `SQAO_LIVE_DERIV_COMPLETE_OS_GITHUB.zip`

Descarga el artifact desde la ejecución satisfactoria del workflow en GitHub Actions. El artifact es una distribución de código fuente; no instala ni inicia automáticamente Render, Tesseract, Python ni el GPT.

### Instalación local
1. Descomprime el ZIP.
2. Instala Python 3.12.
3. Instala Tesseract OCR en el sistema si vas a procesar capturas.
4. Instala dependencias:
   `python -m pip install -r ENGINE/requirements.txt -r API/requirements.txt`
5. Ejecuta pruebas:
   `python -m compileall -q API AI ENGINE CONNECTOR`
   `python -m ENGINE.tests`
   `python -m ENGINE.test_chart_visual_extraction`
   `python -m ENGINE.test_mtf_sync`
6. Configura el servicio/API siguiendo la documentación del repositorio y verifica `/health` antes de usar el GPT.

## Seguridad y límites
- READ-ONLY / RESEARCH-ONLY: no hay envío, modificación ni cierre de órdenes.
- No incluyas secretos, claves ni tokens en el ZIP, instrucciones GPT o repositorio.
- Capturas y OCR no sustituyen OHLC cerrado con timestamp.
- La puerta MTF exige D1/H4/H1/M15/M5/M1 sincronizados.
- Costes desconocidos o evidencia OOS insuficiente => NO_TRADE.
- Un CI verde valida las pruebas ejecutadas; no demuestra rentabilidad ni disponibilidad permanente del servicio Render.
