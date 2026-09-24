# MEDICION_CMP_CC_POST_C.md

Fecha UTC: 2026-09-21T20:42Z

## Contexto

Post Incremento C (corpus atributo) + hotfix `gpt-6-astra` (omitir `temperature=0`).

## Runs

| Rol | run_id | N |
|---|---|---|
| Baseline | `20260921T105853Z_4f3d3488` | 53 CMP/CC |
| Actual (parte 1) | `20260921T201017Z_40578a2f` | CMP01–19 |
| Actual (parte 2) | `20260921T202225Z_8d6a954d` | CMP20–48 + CC01–05 |
| Merge | `incremento_c/medicion_cmp_cc_merged.jsonl` | **53** |

## Resultado vs baseline

| Status | Baseline | Actual | Δ |
|---|---|---|---|
| FAIL_GROUNDING | 50 | 50 | 0 |
| PARTIAL_CAPABILITY | 2 | 2 | 0 |
| PASS_RESOLVED | 1 | 1 | 0 |

**Transiciones de status: 0.** El oráculo CMP/CC no mejoró en agregado tras el enriquecimiento de corpus.

Casos no-FAIL estables: `CC02` PASS_RESOLVED; `CMP12`/`CMP40` PARTIAL_CAPABILITY.

## Fix modelo (sí impacto en smoke)

Causa de `ModelInvocationError` / `model_resolve_full_exhausted`:

> `gpt-6-astra` rechaza `temperature=0` (solo default=1).

Hotfix QA: `semantic_mode.azure_chat_options` + proposer/verifier/classifier. Smoke post-fix: ya no hay `PROVIDER_ERROR` por temperature.

## Lectura

- El índice candidato **sí** indexa atributos (`cmp-attr-*`, 219 docs) y Search los rankea en consultas directas.
- El fallo CMP\* sigue siendo **grounding de oráculo** (facets `initial_set`/`differences`/atributos), no caída del modelo.
- Smoke manual aún ve retrieval incorrecto en algunos prompts (p. ej. “Documento digital” ante beneficios/exclusiones) → ranking/filtros/plan de conocimiento, no solo cobertura de corpus.

## Artefactos

- `incremento_c/medicion_cmp_cc_vs_baseline.json`
- `incremento_c/smoke_post_temp_fix.json`
- `deploy/corp-8447/_hotfix_gpt6_temperature.py`
- `tests/unit/test_azure_chat_temperature.py` (2 passed)

## Siguiente apalancamiento (no más corpus ciego)

1. Revisar 3–5 FAIL_GROUNDING típicos (Platinum requisitos/beneficios/compare) en `turnos.jsonl` vs evidencia Search.
2. Ajustar retrieve/filtros o composición para preferir `source_scope=qa_eligible_attr` / `cmp-attr-*` cuando la pregunta pide atributo.
3. B3 fastpath multi-tarea si el plan omite sub-intenciones.
