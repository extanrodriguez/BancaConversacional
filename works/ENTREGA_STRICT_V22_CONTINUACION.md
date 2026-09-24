# Informe final — Potenciación strict-v2.2 (continuación)

Fecha UTC: 2026-09-21

## Versión identificada

| Campo | Valor |
|---|---|
| Código cognitivo | `potenciacion-strict-v2.2` |
| Oráculo | `strict_v2.2` |
| Cliente QA | `726588` (lectura) |
| Entorno | QA `:8447` · lab_fallback · Core no vivo · **sin PROD** |
| Backend .NET / frontend / WS | **intactos** (solo capa cognitiva + evaluador/scripts) |
| Matriz canónica | `works/qa_runs/20260921T004314Z_strict_v22_oracle_guide` |
| Reevaluación fuente | `works/qa_runs/reeval_strict_v2.2_20260920T203909Z_d83c1c54` |
| Histórico bruto (intacto) | `works/qa_runs/20260920T203909Z_d83c1c54` |
| P0 histórico (intacto) | `works/qa_runs/20260920T201855Z_c6702543` |

## Correcciones de esta iteración

### 1. P12 — ventana temporal explícita
- Módulo `src/genesis_cognitive/context/upcoming_payment_window.py`
- Guardrail + `_upcoming` clasifican **upcoming / overdue / beyond / missing**
- Respuesta declara **fecha de referencia**, **America/Santo_Domingo**, **intervalo 30 días**
- Tener fecha de pago ≠ pago próximo (probado pasado / hoy / futuro)
- Oráculo: respuesta legada sin ventana → `payment_window_resolved=N` (ya no aprueba)
- Smoke local OK; QA remoto requiere **redeploy** para ver el texto nuevo en UI

### 2. Comparaciones con valores concretos
- `_contrast_catalog_attributes` muestra extractos «valor» por producto
- Evita sustituir contenido disponible por solo «documentado/no documentado»
- Se conserva rechazo Platinum←Joven (`_evidence_applies_to_catalog_product` + `FAIL_GROUNDING`)

### 3. Auditoría vs respuesta (cancelación L09/MIX10)
- Cliente: lenguaje natural («monto para cancelar…»)
- Telemetría: `field_path`, `field_origin`, `source_fetched_at`, `payoff_accredited` en `decision_trace` / `audit`
- Oráculo: **nombrar `payoff_amount` en el texto no acredita**; exige mapeo en audit
- Sin audit en turnos históricos → PARTIAL (correcto)

### 4. Oráculos guía (78 pendientes → 0)
- `_evaluate_guide_typed_oracle` tipado por familia/expected de `casos_236.json`
- `need_map` personal restringido (deja de fallar IG* por heurística de fecha)
- Conteos canónicos 236:

| Estado | n |
|---|---|
| PASS_RESOLVED | 63 |
| PASS_CLARIFICATION_EXPECTED | 1 |
| PARTIAL_CAPABILITY | 21 |
| FAIL_INTERPRETATION | 41 |
| FAIL_RETRIEVAL | 58 |
| FAIL_GROUNDING | 51 |
| FAIL_STATE | 1 |
| PENDING_EVALUATION | **0** |

### 5. Taxonomía de los ~99+ fallos (agrupados)

| Clase | n (aprox.) | Tipo | Notas |
|---|---|---|---|
| FAIL_GROUNDING producto–evidencia (CMP/CC) | 51 | Sistema / KB | Cruce o falta evidencia aplicable; filtro local no desplegado en `:8447` |
| FAIL_RETRIEVAL / topic_overlap guía | 58 | Sistema / datos / wording | KB incompleta o respuesta no alineada al tópico |
| provider_error en turnos | 30 | Dependencia | Errores de proveedor en corrida histórica |
| Facetas personales incompletas | ~10 | Sistema / evaluador | due_date, debt, etc. |
| P12/L09/MIX10 → PARTIAL | 3 | Esperado post-estricto | Ventana/audit nuevos; redeploy + re-run live |

Detalle: `works/qa_runs/_v22_fail_taxonomy.json`

### 6. Guía con columna fix
- `works/validacion_guia_fix/Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.MD`
- `works/validacion_guia_fix/Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.html`
- Una fila por ID; histórico conservado; fix con resultado, run_id y evidencia
- Conteos fix: RESUELTO 16 · PARCIAL 69 · FALLA 151

### 7. Capturas chat
- Automatización **desbloqueada** con Chrome instalado (`channel=chrome`; sin descargar Chromium Playwright)
- Run nuevo: `20260921T004500Z_chrome_p0fix` — 8/8 (P12, L09, MIX10, CC02, L10, P01, P02, L12)
- Run previo P0: `20260920T200903Z_ba3ee002` (40 casos) — conservado; shots nuevos fusionados donde aplica
- Resto de 236: **PENDING_UI** — ver `works/qa_runs/RECORRIDOS_CAPTURA_UI_PENDIENTES.md`
- HTTP 200 ≠ conversación funcional (acreditado con capturas reales de hilo)

## Pendiente operativo

1. Redeploy capa cognitiva a `:8447` (sin tocar backend externo) para P12 ventana + audit cancelación en vivo
2. Re-ejecutar P0 live post-deploy y re-capturar P12/L09/MIX10/CC02/L10
3. Completar capturas UI del resto de la guía
4. Resolver FAIL_GROUNDING CMP* con KB/evidencia de producto correcta en QA

## Registros históricos conservados

No se reescriben corridas previas; solo carpetas `reeval_*` y materializaciones nuevas.
ZIP de entrega anterior permanece; este informe añade artefactos v2.2-oracle-guide.

## Hash del ZIP (fuera del archivo)

- ZIP: `works/qa_runs/EVIDENCIAS_STRICT_V22_CONTINUACION_20260921T005109Z.zip`
- SHA256: `2F9FCA6C32BD4576182295F440338B242DFDA2B4B6DAE9C5741104638632BF06`
- Archivo hash: `works/qa_runs/EVIDENCIAS_STRICT_V22_CONTINUACION_20260921T005109Z.sha256`
