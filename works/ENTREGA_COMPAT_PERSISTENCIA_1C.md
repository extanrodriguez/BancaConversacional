# Entrega — compatibilidad y persistencia 1C

Sin cambios en Azure/Foundry/índices/orquestador externo. QA Azure real no ejecutada.

## 1. Endpoint consumidor (solo lectura del backend externo)

**Ruta productiva: `POST /turn`**, no `/inspect`.

Evidencia en `BSC.genesis.conversational.backend` (sin modificar):

| Archivo | Función / detalle |
|---|---|
| `.../Clients/NvidiaChatClient.cs` | `ResolveTurnEndpoint` exige path `/turn` (`LLM_TURN_ENDPOINT`) |
| mismo | `QueryRagAsync` → `PostAsync(_turnEndpoint, …)` |
| mismo | `ReplyAsync` / `ClassifyAsync` consumen esa respuesta |
| mismo | `LoadInitialContextAsync` también POST a `/turn` con `context_info` |
| `appsettings.json` | `PrivateRagEndpoint` legacy `…/turn` (log indica que ya no se usa para evitar fallback) |

### Respuestas no exitosas

En `QueryRagAsync` (líneas ~249–258): si `!response.IsSuccessStatusCode` → `RagFrontResponse{ HasError=true }` — **sin reintento**.
`ReplyAsync`: si error → mensaje genérico al socket (“No pude completar la consulta…”).
**No hay retry** de la petición HTTP.

### Incertidumbre de config

El host/puerto efectivo depende de `LLM_TURN_ENDPOINT` / opciones en runtime del orquestador (no disponible en este entorno). Se confirma el **path** `/turn`; no se asume que `/inspect` sea productivo.

## 2. Compatibilidad del 409 — NO preservado como contrato

| Capa | Hallazgo |
|---|---|
| `schemas/app_channel_response.schema.json` | `client_response` **required** y tipo **string** → `null` inválido |
| Consumidor | HTTP ≠ 2xx → `HasError` + fallback; no entiende `SESSION_CONFLICT` |
| Conclusión | **No se declara preservado** el contrato con HTTP 409 + `client_response=null` |

### Estrategia cognitiva aplicada (compatible)

1. **Serialización por conversación** (`conversation_gate.py`): RLock local + candado Redis opcional.
2. Conflicto residual CAS → **HTTP 200** + `status=SESSION_BUSY` + `client_response` string (sin saldo inventado, sin reintentar solo la escritura).
3. `/turn` **no** reescribe `SESSION_BUSY` a `VALID_CONTRACT`.

## 3. Cobertura de la ruta usada (`/turn`)

- NL: `/turn` → `inspect` (con gate + CAS).
- `context_info`: gate + `_persist_core_context` con `expected_revision`; conflicto → 200 `SESSION_BUSY`.
- Fastpaths/aclaraciones/errores de inspect: commits CAS; busy compatible.

## 4. Redis real local

**Pendiente.** Docker CLI presente pero engine no activo (`dockerDesktopLinuxEngine` pipe ausente). No se atribuye éxito.

Procedimiento: `works/REDIS_CONCURRENCY_PROCEDURE_1C.md`  
Harness: `tests/manual/redis_http_concurrency_harness.py`

## 5. Evidencia sintética aislada

- Eliminado `GENESIS_SYNTHETIC_KB_TEST` del flujo desplegable.
- Inyección: `rate_context_guardrail.set_definition_evidence_override(...)` solo en tests.
- Sin evidencia: se declara definición no disponible y se conserva la parte personal.

## 6. Cambios cognitivos

- `context/conversation_gate.py` (nuevo)
- `demo/contract_inspector_app.py` (gate, SESSION_BUSY, `/turn` context CAS)
- `router/rate_context_guardrail.py` (override inyectable)
- tests + docs anteriores

**No modificado:** `BSC.genesis.conversational.backend/`

## Pruebas ejecutadas (reales)

```text
84 passed, 2 skipped
```

(suites 1C close/1C/1B/1/field/fase1; skip = QA Azure)

## Limitaciones pendientes

- Validación Redis multi-proceso HTTP con barreras (procedimiento listo).
- QA Azure real.
- Candado Redis solo si hay URL; sin Redis, serialización es in-process.
