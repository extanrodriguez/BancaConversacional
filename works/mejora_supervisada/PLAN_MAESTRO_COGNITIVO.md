# PLAN_MAESTRO_COGNITIVO.md

Plan único A–E. Esta sesión ejecutó **A + B parcial**.

| Ítem | Descripción | Estado verificado |
|---|---|---|
| A | Baseline, trazabilidad, filtros, promote-con-aprobación, modelo efectivo | **HECHO** (DESPLEGADO_QA) |
| B | Grounding por atributo + compare parcial ≠ completo + budget evidencia | **PARCIAL HECHO** |
| B3 | Fastpath multi-tarea / correcciones foco | Pendiente (causa común; no reescritura) |
| C | Corpus CMP/CC oráculo + ranking medido | **HECHO corpus** (219 docs; medición subset pendiente) |
| D | Bandeja revisión + evaluador Azure sombra | Pendiente (fuera de sesión) |
| E | Regresión 236 + ZIP + rollout | Pendiente |

## A — detalle

| Actividad | Problema | Criterio | Evidencia |
|---|---|---|---|
| A1 Baseline | Confusión Foundry vs `/turn` | Health/ready/smoke OK | `evidencia_baseline/baseline.json` |
| A2a/b Promote | Votos≠aprobación; inflación | `--apply` exige approved-json; dedup | tests unit + script |
| A2c Filtros | Ampliación silenciosa | No strip filter | test + código |
| A2h Rerank | Etiqueta falsa Semantic Ranker | Flag + `local_lexical_bonus` | código |
| A2j Modelo | Declarado≠efectivo | Doc + semantic_mode | MODELO_EFECTIVO |
| A3 Deploy | Código solo local | Hotfix `:8447` | smoke post |

## B — detalle

| Actividad | Estado | Notas |
|---|---|---|
| B1 Grounding atributo | HECHO | `ATTRIBUTE_MARKERS` + reason `attribute_missing` |
| B2 Compare parcial | HECHO | `status=partial` + banner en respuesta |
| B2 Budget | HECHO | 3200 content / 2800 compare clip |
| B3 Interpretación | PENDIENTE | Sin nuevo sistema |

## Siguiente acción precisa

1. Subset CMP*/CC* medido vs baseline `20260921T105853Z_4f3d3488`
2. Estabilizar invocación `gpt-6-astra` (errores `model_resolve_full_exhausted` en smoke C)
3. B3 fastpath multi-tarea
4. Incrementos D/E según prioridad de negocio
