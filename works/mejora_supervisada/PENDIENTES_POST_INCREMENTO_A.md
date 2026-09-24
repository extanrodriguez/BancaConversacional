# PENDIENTES_POST_INCREMENTO_A.md

Actualizado: 2026-09-21 (post Incremento C)

## Ejecutado

| Paso | Resultado |
|---|---|
| Incremento A + B parcial | HECHO — ver `ENTREGA_INCREMENTO_A.md` |
| Índice candidato activo | `bsc-kb-qa-vnext-20260921` en `:8447` |
| GPT-6 en `/turn` | Activo (`deployment=gpt-6-astra` en audit); inestable bajo algunas queries |
| Foundry Search → candidato | Usuario reportó selección; playground ≠ `/turn` |
| Incremento C corpus atributos | **HECHO** — 23 docs; índice **219**; ver `ENTREGA_INCREMENTO_C.md` |

## Pendiente técnico

| ID | Ítem | Notas |
|---|---|---|
| Medición | Subset CMP*/CC* vs baseline | **HECHO** — Δ status = 0; ver `MEDICION_CMP_CC_POST_C.md` |
| Retrieve atributo | Preferir `cmp-attr-*` en queries de requisito/beneficio/tasa | Smoke aún trae “Documento digital” en algunos casos |
| B3 | Fastpath multi-tarea | No reescrito en A |
| D | Bandeja + juez Azure sombra | Fuera de A/C |
| E | Matriz 236 + ZIP | Fuera de A/C |
| Ops | Renovación token Entra ciclo largo | Pendiente operativo |

## Qué ya está OK (no rehacer)

- Índice candidato + enriquecer CMP atributos (C)
- Fix `temperature` para `gpt-6-astra` en proposer/verifier
- Filtros sin strip, promote con aprobación, grounding atributo, compare parcial
- Backend .NET / FE / WS intactos
- `bsc-kb-conocimiento` intacto (no tocar)
