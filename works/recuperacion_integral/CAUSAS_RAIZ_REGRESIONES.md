# CAUSAS_RAIZ_REGRESIONES.md

Fecha: 2026-09-21 · Fase P0 recuperación (en curso)

## Método

Hipótesis → prueba → confirmar/descartar. Sin parches por frase.

## Hallazgos confirmados

### H1 — Índice candidato débil en institucional (CONFIRMADA)

| | |
|---|---|
| Síntoma | «misión/visión» devolvía contacto o texto de tarjeta |
| Prueba | Search `bsc-kb-qa-vnext-20260921` vs `bsc-kb-conocimiento`: en protegido rankea `fase1-mision-y-vision`; en candidato «misión del banco» rankeaba contacto |
| Mecanismo | El candidato sí tenía `vf01-r080/r082` pero sin anclas de consulta; `public_reference` de contacto ganaba el ranking vía `azure resolve_full` |
| Fix | (1) Corpus institucional VF01 enriquecido (`inst-vf01-*`, índice 222) (2) Rerank local favorece título Misión/Visión (3) Shortcut familia `kb_institutional` para institucional puro → plan local + FAQ/Search |
| Evidencia | Antes: `diag_smoke_live.json` (contacto/tarjeta). Después: `diag_smoke_post_fix.json` + retest limpio — misión/visión VF01 vía `shortcut:kb_institutional` |

### H2 — `gpt-6-astra` + `temperature=0` (CONFIRMADA, ya corregida)

| | |
|---|---|
| Síntoma | `ModelInvocationError` / «No pude completar la interpretación semántica» |
| Prueba | Chat Completions: 400 «temperature does not support 0» |
| Fix | `azure_chat_options` omite temperature en gpt-6/astra (hotfix previo) |

### H3 — Local ≠ QA en 3 archivos (CONFIRMADA, no causa de lo visto en institucional)

| Archivo | Nota |
|---|---|
| `azure_plan_turn.py` | Local más nuevo que QA (pre-hotfix P0) |
| `field_guardrails.py` | Local más nuevo — **no desplegado** en el smoke pre-fix |
| `contract_inspector_app.py` | Local más nuevo — **no desplegado** |

Las regresiones institucionales se reprodujeron **en QA** con el código entonces desplegado + índice candidato. No atribuir a cambios locales no publicados.

### H4 — CMP*/CC* FAIL_GROUNDING (PREEXISTENTE / no movido por C)

Medición post-C: Δ status = 0 vs baseline. No es la misma causa que institucional.

## Hipótesis abiertas

| ID | Hipótesis | Estado |
|---|---|---|
| H5 | Fastpath/compound omite subtareas en multi-intención | Pendiente (B3) |
| H6 | Verifier gpt-6 altera planes correctos | Pendiente — monitorear tras shortcut institucional |
| H7 | Caché Redis de respuestas erróneas | No evidenciado aún |
| H8 | Rollback a `gpt-4o-mini` mejora interpretación personal compleja | No probado; disponible vía PLAN_ROLLBACK R1 |

## Cambios pospuestos (contención)

- Promote de ejemplos / learning
- Ajustes experimentales de ranking más allá del boost institucional
- Ampliar corpus CMP ciego sin retrieve atributo medido
