# SQAO LIVE DERIV V3.2.1

Paquete candidato del complemento, basado en la integración V3.2.0.

## Contenido
- `manifest.json`: identidad, versión, controles de seguridad, temporalidades y rutas.
- `INSTRUCTIONS.md`: instrucciones operativas para el complemento.
- `schemas/visual-audit.schema.json`: contrato mínimo de auditoría visual.
- API: reutiliza `GPT/openapi.yaml`; la versión del servicio sigue siendo 2.6.0 y no debe confundirse con la versión del complemento.

## Instalación / configuración
1. Importar las instrucciones de `INSTRUCTIONS.md` en el campo de instrucciones del complemento/GPT.
2. Importar las operaciones desde `GPT/openapi.yaml` como Action OpenAPI.
3. Configurar el secreto `X-SQAO-Key` en el gestor de autenticación de Actions; nunca pegarlo en instrucciones, repositorio, capturas o mensajes.
4. Mantener `/health` sin autenticación según el contrato actual.
5. Habilitar únicamente las operaciones GET declaradas en OpenAPI.
6. Verificar que el endpoint de salud devuelve la versión de servicio esperada y que el conector está activo.
7. Ejecutar las pruebas de regresión del repositorio antes de distribuir el complemento.

## Requisitos del motor visual
Python 3.10 o superior. Dependencias OCR: Pillow, pytesseract y el binario Tesseract. El motor debe fallar de forma controlada si falta una dependencia.

## Estado de capacidades
Incluido: intake de imágenes, SHA-256, OCR tokenizado, bounding boxes, detección de etiquetas y gate de timestamps de captura.
No certificado todavía: segmentación robusta de paneles, asociación de curvas/leyendas, extracción numérica automática de todos los indicadores, reconciliación visual-API y sincronización de velas basada en metadatos de captura.

## Seguridad
El complemento es READ_ONLY / RESEARCH_ONLY. No contiene ni debe incorporar endpoints de trading. La salida permanece NO_TRADE y execution_eligible=false.
