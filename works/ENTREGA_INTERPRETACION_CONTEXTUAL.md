# Entrega — Interpretación contextual BSC

Fecha: 2026-09-19.

## Cambios (capa cognitiva)

| Archivo | Cambio |
|---|---|
| `model_input/model_input_builder.py` | Proyección contextual v1: campos aplicables, máscara, completitud |
| `brain/semantic_field_catalog.py` | **Nuevo** catálogo semántico de campos/tipos/convenciones |
| `brain/azure_plan_turn.py` | Envelope enriquecido; bridge no captura multi-intención |
| `router/faq_guardrail.py` | No tratar «tarjeta joven/mi tarjeta» como definición de cliente |
| `brain/plan_executor.py` / `turn_plan.py` | Procesos KB (ya en hotfix previo; conservado) |
| `tests/unit/test_matriz_aceptacion_contextual.py` | Matriz AX |
| `scripts/run_contextual_acceptance.py` | Runner local 236 + AX |
| `works/*` | Diagnóstico, mapa, resultados, brechas, matriz, casos |

**Backend externo** `BSC.genesis.conversational.backend`: no modificado (solo lectura).

## Pruebas

| Suite | Resultado |
|---|---|
| `test_matriz_aceptacion_contextual` + UX bridge + cierre V4 + fase1 | **38 passed** |
| Runner local AX | **7/7 PASS** |
| Guía 236 | 210 `PASS_SAFE` (ejecución local); 26 multi-turno `NOT_EXECUTED` |
| QA lab 726588 | saldo tarjeta joven OK; fecha pago aclara; reclamación OK; fallecidos OK |

## Métricas por etapa (local)

- Proyección: sin saldos; `applicable_fields` por tipo.
- Resolución alias: tarjeta joven → entity único.
- Bridge procesos: telemetrado `field_fastpath:*`.
- Etiquetas históricas **no** usadas como oráculo.

## Límites

- Sin transacciones / otros clientes / PROD / Foundry publish.
- Core vivo puede no tener Tarjeta Joven → `NOT_APPLICABLE` remoto.
- `PASS_SAFE` ≠ Cumple de la guía.

## QA / rollback

Despliegue: copiar módulos listados a `/opt/genesis-cognitive-8447/Genesis_v2` + `systemctl restart genesis-cognitive-8447`.  
Rollback: restaurar `.py` previos desde backup del host o paquete anterior.  
Redis: no tocar `.env` Entra en este cambio.

## Paquete

Ver `works/MANIFEST_INTERPRETACION_CONTEXTUAL.json` y ZIP asociado.
