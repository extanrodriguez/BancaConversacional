# ENTREGA_RECUPERACION_INTEGRAL.md

Fecha UTC: 2026-09-21T21:05Z · Estado: **CANDIDATO_PARCIAL — NO cierre integral**

## Qué se hizo (P0)

1. **Contención**: snapshot `works/recuperacion_integral/snapshots/20260921T204551Z` (código + SHA). Sin Git.
2. **Local vs QA**: 9 MATCH / 3 DIVERGED (local adelantado en `azure_plan_turn`, `field_guardrails`, `contract_inspector_app`).
3. **Inventario 236**: `MATRIZ_RECUPERACION_CAPACIDADES` — preliminar por runs (38 REGRESION_CONFIRMADA proxy, 59 FALLO_PREEXISTENTE, 137 estables en runs).
4. **Causa compartida institucional (H1) confirmada y corregida**:
   - Corpus VF01 misión/visión en candidato
   - Rerank local anti-contacto
   - Shortcut familia `kb_institutional` (no parche por frase)
5. **Re-smoke familias** post-fix: misión/visión OK; portafolio/definición/cancelación/compare/multi OK.
6. **Subset revalidación** de regresiones proxy: en curso (`_recup_subset_*`).

## Capacidades recuperadas (evidencia live)

| Familia | Antes | Después |
|---|---|---|
| Institucional misión/visión | Contacto / texto ajeno | Texto VF01 vía `kb_institutional` |
| Temperature gpt-6 | ModelInvocationError | OK (fix previo) |
| Portafolio listado | OK | OK |
| Definición saldo disponible | OK | OK |
| Cancelación préstamos | OK | OK |
| Compare catálogo | OK | OK |

## Abierto — no declarar recuperación integral

- Regresión 236 completa + GUIA_CON_FIX con capturas
- 38 REGRESION_CONFIRMADA proxy aún por revalidar live (subset en curso)
- CMP*/CC* FAIL_GROUNDING (preexistente; Δ=0 post Incremento C)
- Local `field_guardrails` / `contract_inspector_app` no alineados con QA
- RESULTADOS_236 pendiente del run completo

## Artefactos

| Entregable | Ruta |
|---|---|
| Matriz | `works/recuperacion_integral/MATRIZ_RECUPERACION_CAPACIDADES.md` |
| Baseline diffs | `works/recuperacion_integral/BASELINE_Y_DIFERENCIAS.md` |
| Causas | `works/recuperacion_integral/CAUSAS_RAIZ_REGRESIONES.md` |
| Rollback | `works/recuperacion_integral/PLAN_ROLLBACK.md` |
| Smokes | `diag_smoke_live.json`, `diag_smoke_post_fix.json` |
| Esta entrega | `ENTREGA_RECUPERACION_INTEGRAL.md` |

## Condición de cierre (aún no)

No hay recuperación integral mientras existan regresiones confirmadas abiertas o capacidades acreditadas sin revalidar. Este es un **candidato parcial** identificado.
