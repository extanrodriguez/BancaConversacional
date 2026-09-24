# Prompt Cursor — Validación Guía con columna Fix

## Objetivo

Derivar de la guía de pruebas conversacionales BSC una hoja/tabla con columna **Fix**
por escenario, y acreditar cada fila con **capturas reales de la UI** existente
(servicio cognitivo QA), sin modificar frontend ni orquestador externo.

## Entrada

- Guía e inventario: `works/insumos/BSC_Potenciacion_Lunes/evaluacion/`
- UI QA: `http://20.127.25.24:8447/` (HTML servido por la capa cognitiva)
- Cliente lectura: `726588` · `lab_fallback`
- Versión cognitiva bajo prueba (registrar en manifiesto)

## Alcance

- **Dentro:** probar UI existente, capturar pantallas saneadas, rellenar columna Fix.
- **Fuera:** cambios a frontend, WebSocket, `BSC.genesis.conversational.backend`, PROD.

## Procedimiento

1. Abrir la UI en el endpoint QA. Si no carga o exige orquestador ausente, documentar el bloqueo concreto y marcar evidencia visual como `PENDING_UI`.
2. Para cada escenario P0 (mínimo) y muestra de la guía: ejecutar el diálogo en la UI, capturar el hilo visible, sanear montos/máscaras.
3. Completar `works/qa_runs/<run>/guia_columna_fix.md` con columnas:
   `case_id | esperado | obtenido_ui | status | Fix | captura`
4. La columna **Fix** describe la corrección cognitiva aplicada o pendiente (no inventar fix de UI).
5. No sustituir capturas del chat por renders desde logs JSONL.

## Criterio de cierre

- Guía derivada con Fix entregada.
- Capturas reales por escenario, o bloqueo UI documentado sin simulacros.
