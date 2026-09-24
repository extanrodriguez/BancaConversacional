# ENTREGA_INCREMENTO_C.md

Fecha UTC cierre: 2026-09-21T20:00Z · Alcance: **Incremento C — corpus CMP atributos**

## Resumen

Se enriqueció el índice candidato `bsc-kb-qa-vnext-20260921` con **23 chunks de atributo** (requisitos, beneficios Puntos, exclusiones, metodología de tasa, features) derivados solo de `Knowledge_Base/excel_vf01/Tarjeta_de_Crédito.md`. **No** se inventaron tasas numéricas por producto. `bsc-kb-conocimiento` permanece intacto.

## Etiquetas

| Ítem | Etiqueta |
|---|---|
| Gaps CMP documentados | `IMPLEMENTADO_LOCAL` (`incremento_c/corpus_attribute_gaps.json`) |
| Generación + upload atributo | `VALIDADO_QA` (Search: 23 docs `cmp-attr-*`) |
| Índice candidato post-C | **219** docs (antes 196) |
| Smoke requisitos Platinum | `VALIDADO_QA` — responde texto VF01 de requisitos |
| Smoke compare Platinum/Infinite | `VALIDADO_QA` — evidencia producto + features enriquecidas |
| Smoke beneficio / exclusión / tasa vía `/turn` | `PARCIAL` — Search recupera OK; `/turn` falló por `ModelInvocationError` (`gpt-6-astra`, `model_resolve_full_exhausted`) |
| Tasas % por producto | **No inventadas** (solo metodología VF01) |
| Matriz CMP*/CC* vs baseline | Pendiente (siguiente medición) |

## Artefactos

| Archivo | Uso |
|---|---|
| `scripts/enrich_cmp_attribute_corpus.py` | Build + embed + `mergeOrUpload` |
| `incremento_c/attribute_docs.jsonl` | 23 docs fuente |
| `incremento_c/corpus_attribute_gaps.json` | Diagnóstico previo |
| `incremento_c/smoke_cmp_post_enrich.json` | Smoke #1 |
| `incremento_c/smoke_cmp_retry.json` | Smoke #2 (audit `gpt-6-astra`) |

## Distribución de chunks

| Atributo | N | Productos |
|---|---|---|
| `requirement` | 5 | Clásica, Gold, Platinum, Infinite, Joven |
| `benefit` | 4 | Clásica, Gold, Platinum, Infinite |
| `exclusion` | 4 | Platinum, Infinite, Gold, Joven |
| `rate` | 5 | metodología financiamiento (sin % inventado) |
| `features` | 5 | fichas enriquecidas VF01 |

## Criterios de aceptación

- [x] Fuentes aprobadas (VF01) sin tocar índice protegido
- [x] Chunks con marcadores de atributo indexados en candidato
- [x] Search recupera `cmp-attr-*` en consultas requisito/beneficio/exclusión/tasa
- [x] Smoke `/turn` requisitos Platinum con contenido real de requisitos
- [x] Smoke compare Platinum/Infinite con evidencia
- [ ] Subset CMP*/CC* medido vs baseline (fuera de C estricto; siguiente)
- [ ] Smokes beneficio/exclusión/tasa estables en `/turn` (bloqueados por invocación modelo)

## Smoke post-enrich (cliente 726588)

| Pregunta | HTTP | Nota |
|---|---|---|
| requisitos visa platinum | 200 | Cita requisitos VF01 (cédula, antigüedad laboral, renta ≤22%, ingresos, edad 18–70) |
| beneficios puntos santa cruz visa platinum | 200 | Fallo modelo `gpt-6-astra` (no corpus); Search sí rankea `cmp-attr-benefit-puntos-visa_platinum` |
| exclusiones recompensas visa infinite | 200 | Idem ModelInvocationError; Search sí trae `cmp-attr-excl-visa_infinite` |
| cómo se calcula la tasa… | 200 | Idem; Search trae `cmp-attr-rate-*` |
| compara visa platinum e infinite | 200 | Evidencia Platinum/Infinite; features enriquecidas visibles |

## No declarado

- Tasas porcentuales por producto (no están en VF01 de forma usable)
- Cierre de FAIL_GROUNDING en matriz CMP completa
- Estabilidad 100% de `gpt-6-astra` bajo carga

## Siguiente

1. Medición subset CMP*/CC* vs baseline `20260921T105853Z_4f3d3488`
2. Investigar `ModelInvocationError` / rate-limit de `gpt-6-astra` (fallback a `gpt-4o-mini` si persiste)
3. B3 fastpath multi-tarea
4. Incrementos D/E según plan maestro
