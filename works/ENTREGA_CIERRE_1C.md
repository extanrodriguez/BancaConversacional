# Entrega cierre pendientes 1C

Fecha: 2026-09-17. Sin llamadas remotas, sin despliegues, sin cambio de índices.
QA Azure real: **sigue pendiente** de autorización.

## Diff / archivos modificados

| Archivo | Cambio |
|---|---|
| `src/genesis_cognitive/context/reactive_store.py` | `copy_session`; get/put sin refs compartidas; `create_session` CAS `expected_revision=0` |
| `src/genesis_cognitive/context/redis_session_store.py` | `create_session` con `expected_revision=0` |
| `src/genesis_cognitive/demo/contract_inspector_app.py` | `/inspect` + `_persist_core_context` con CAS; conflicto → **409** sin respuesta definitiva; sin put prematuro |
| `src/genesis_cognitive/router/rate_context_guardrail.py` | **nuevo** — tasa contextual (préstamo/DAP/foco) + mixtas |
| `src/genesis_cognitive/router/field_guardrails.py` | steps `mixed_pk` / `personal_rate` |
| `src/genesis_cognitive/router/snapshot_guardrails.py` | quita overfit “mi tasa”→préstamo |
| `src/genesis_cognitive/router/faq_guardrail.py` | mixtas con “y qué significa” |
| `tests/unit/test_cognitive_stabilization_stage1c_close.py` | **nuevo** — HTTP CAS, tasa, mixtas |
| `tests/unit/test_cognitive_stabilization_stage1c.py` | refs mutables corregidas |

**No modificado:** `BSC.genesis.conversational.backend/`, frontend, WebSocket de producción, contratos externos, corpus FAQ productivo.

## Concurrencia HTTP

- Store local: **ReactiveSessionStore in-memory (simulado)**. `GENESIS_REDIS_URL` / `REDIS_URL` ausentes en esta corrida.
- Redis real: soportado vía `RedisSessionStore` (WATCH) si se configura URL; **no ejercitado aquí**.
- `/inspect` lee revisión → trabaja sobre copia → `put_session(..., expected_revision=...)`.
- Conflicto: HTTP **409** `SESSION_CONFLICT`, `client_response=null` (no se afirma éxito sobre estado no confirmado).
- No se reintenta el guardado con revisión nueva.
- Creación concurrente: `create_session` CAS; perdedor recarga o 409.

Pruebas HTTP: `test_http_concurrent_turns_same_session_one_conflict`, `test_http_two_sessions_same_client_isolated`, `test_http_distinct_clients_isolated`, `test_http_concurrent_session_create_same_conv`.

Limitación: con timing sin solape real, dos 200 secuenciales son válidos; con solape debe aparecer 409.

## Tasa contextual

| Caso | Resultado |
|---|---|
| Solo préstamo | tasa préstamo |
| Solo DAP | tasa DAP |
| Ambos sin foco | aclaración (no asume préstamo) |
| Ambos con foco DAP | tasa DAP |
| Varios préstamos | aclaración |
| “Qué significa tasa” | FAQ / conocimiento |

## Mixtas

“¿Cuál es la tasa de mi préstamo y qué significa?” → tasa personal + definición (FAQ o `[evidencia-sintetica-test]` vía `GENESIS_SYNTHETIC_KB_TEST=1`). Varios préstamos → clarifica **sin perder** pendiente de definición.

## Pruebas ejecutadas

```text
119 passed, 2 skipped
```

(skip = QA Azure real ×2)

## Riesgos / no ejecutado

- Redis multi-réplica real no validado en esta máquina.
- `/turn` y webhooks orch: CAS parcial vía `_persist_core_context`; path `/turn` legacy puede seguir distinto — revisar si se usa en lab.
- Mixta sin FAQ ni flag sintético: declara definición no resuelta (correcto; no inventa).
- QA Azure real: no ejecutada.
