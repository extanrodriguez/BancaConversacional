# Validación final local — persistencia/concurrencia 1C

## Docker Engine

**No disponible** en esta ejecución (`dockerDesktopLinuxEngine` pipe ausente).

**Acción requerida:** inicia Docker Desktop y avisa para re-ejecutar Redis multi-proceso.
Hasta entonces **no se declara validada** la concurrencia entre procesos.

No se creó ni eliminó ningún contenedor Redis (política: no borrar nombres existentes).

## 1. SESSION_BUSY — compatibilidad consumidor

| Superficie | Hallazgo | Representación cognitiva |
|---|---|---|
| `app_channel_response.schema.json` | `client_response` string required | SESSION_BUSY NL: HTTP **200** + string |
| `QueryRagAsync` / `ReplyAsync` | Solo `HasError` si HTTP ≠ 2xx; parsea `client_response`/`reply` | 200 + mensaje ocupación; `status=SESSION_BUSY` (no inventa saldo) |
| `LoadInitialContextAsync` | **Cualquier 2xx = éxito**; WebSocket marca `initial_context_load_audit.status=success` sin mirar body | `context_info` busy/conflicto → HTTP **503** + `CONTEXT_LOAD_BUSY` + `persisted=false` (dispara `HttpRequestException` existente) |
| Limitación | Consumidor no conoce `SESSION_BUSY` como enum | NL: texto al usuario. Context load: 503 alineado con error path ya existente. **No se modificó el backend externo.** |

Pruebas: `test_turn_endpoint_maps_busy_without_fake_valid_contract`, `test_context_info_busy_returns_503_not_loaded`.

## 2. Candado (`conversation_gate.py`) — correcciones

| Riesgo previo | Corrección |
|---|---|
| `threading.RLock` + await en corutinas mismo hilo | **`asyncio.Lock`** |
| Redis falla → degradaba a local (`return True`) | Si URL Redis configurada → **fail-closed** (`ConversationGateError`) |
| Sin renovación TTL | Renovación periódica con script dueño-only |
| Commit tras pérdida de candado | `still_owner()` antes de CAS put / context persist |
| Liberación | Script Lua compare-and-del por token |

Protección: gate envuelve lectura→procesamiento→commit en `/inspect` y `context_info` de `/turn`.

Instrumentación de prueba: `test_hold_delay_s` / `test_signal_path` para forzar contención real.

## 3–4. Redis real multi-proceso `/turn`

**No ejecutado** (Docker Engine apagado).

Procedimiento listo: `works/REDIS_CONCURRENCY_PROCEDURE_1C.md`  
Harness: `tests/manual/redis_http_concurrency_harness.py`

## 5. Pruebas ejecutadas (esta corrida)

### Simuladas / in-process (sí ejecutadas)

```text
tests/unit/test_cognitive_stabilization_stage1c_close.py
→ 19 passed, 1 skipped (Redis multi-proceso pendiente Docker)
```

Incluye contención ASGI con delay en sección crítica, asyncio exclusion, 503 context load, SESSION_BUSY en `/turn`.

Regresión adyacente: suites 1C/1B/1/field — OK en corridas previas de la misma sesión de trabajo.

### Redis real entre procesos

**0 ejecutadas — pendientes de Docker Engine.**

## Evidencia sanitizada

- Sin PII bancaria real; datos `SYN-*` / tasas sintéticas.
- Sin credenciales ZIP ni Redis del banco.

## Archivos cognitivos tocados

- `src/genesis_cognitive/context/conversation_gate.py` (reescrito)
- `src/genesis_cognitive/demo/contract_inspector_app.py` (async gate, 503 context)
- `tests/unit/test_cognitive_stabilization_stage1c_close.py`

**No modificado:** `BSC.genesis.conversational.backend/`

## Limpieza

Ningún recurso Docker temporal creado → nada que limpiar.
