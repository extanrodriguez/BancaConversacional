# ENTREGA_INCREMENTO_A.md

Fecha UTC cierre: 2026-09-21 · Alcance: **Incremento A + B parcial**

## Resumen

Se consolidó y desplegó en QA `:8447` las correcciones prioritarias de filtros Search, promote con aprobación, grounding por atributo y compare parcial. **No** se declara GPT-6 ni 236 resueltos.

## Etiquetas

| Ítem | Etiqueta |
|---|---|
| Filtros sin strip | `DESPLEGADO_QA` + `VALIDADO_QA` (unit + smoke) |
| Promote approval gate | `IMPLEMENTADO_LOCAL` + `DESPLEGADO_QA` (script en VM) |
| Dedup feedback votos | `IMPLEMENTADO_LOCAL` + `DESPLEGADO_QA` |
| Grounding atributo | `DESPLEGADO_QA` + `VALIDADO_QA` (unit) |
| Compare partial status | `DESPLEGADO_QA` + `VALIDADO_QA` (smoke muestra banner parcial) |
| Índice candidato | `VALIDADO_QA` (activo) |
| GPT-6 en `/turn` | `PENDIENTE_DEPLOYMENT_GPT6` |
| Foundry index tool | `PENDIENTE_FOUNDRY_INDEX` |
| Matriz 236 / ZIP | No ejecutado (fuera de alcance) |
| Bandeja / juez Azure | No implementado (fuera de alcance) |

## Criterios de aceptación de sesión

- [x] Filtros Search ya no se eliminan en reintento
- [x] Promote no publica sin aprobación
- [x] Compare parcial no se presenta como completo
- [x] Grounding exige atributo cuando aplica
- [x] Modelo/índice efectivos documentados
- [x] Hotfix QA aplicado
- [x] 4 entregables MD

## Smoke post-deploy (726588)

| Pregunta | HTTP | Nota |
|---|---|---|
| qué significa saldo disponible | 200 | Definición OK |
| compara visa platinum e infinite | 200 | Banner **comparación parcial** (honestidad) |
| requisitos visa platinum | 200 | Devuelve ficha; grounding atributo `requirement` puede marcar gap si el chunk no tiene “requisito” |

## Tests

`tests/unit/test_incremento_a_filters_grounding_promote.py` → **4 passed**

## No declarado

- 236 resueltos
- GPT-6 activo en chat orquestado
- Semantic Ranker (solo rerank local opcional)
- Éxito Foundry playground como éxito `/turn`

## Siguiente

1. Enganche GPT-6 al endpoint de `:8447`
2. Foundry → índice candidato
3. Incremento C corpus CMP/CC
