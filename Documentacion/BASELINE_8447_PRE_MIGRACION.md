# BASELINE funcional — :8447 pre-migración Foundry product tools

**Fecha:** 2026-09-21 19:49 (local)  
**Target:** `http://20.127.25.24:8447` (QA)  
**Referencia regresión:** comparar post-cambio contra este documento y la guía  
`works/validacion_guia_fix/Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.MD`

---

## 1. Probes HTTP (ejecutados)

| Probe | Resultado | Latencia |
|-------|-----------|----------|
| GET `/health` | OK — `status=ok`, `env=qa`, `version=0.8.0`, `rag=ready` | ~274 ms |
| GET `/ready` | HTTP **404** (no implementado; usar `/ready/redis`) | ~128 ms |
| GET `/ready/redis` | OK — `ok=true`, Entra MI, session+lock ping true | ~111 ms |
| GET `/pruebas/` | HTTP 200, body ~10.5 KB | ~141 ms |
| POST `/turn` validación | HTTP **422** (context_info sin datos válidos) | ~237 ms |
| POST `/turn` smoke NL | HTTP 200, `status=VALID_CONTRACT`, reply ~570 chars | ~1388 ms |

Smoke NL payload:

```json
{
  "question": "cual es la mision del banco",
  "conversation_id": "baseline-smoke-<ts>",
  "customer_id": "726588",
  "context_info": false
}
```

Campos presentes en respuesta smoke: `app_channel`, `core_channel`, `audit`, `rag_status`, `reply`, `message`, `content`, `content_format`, `rich_content`, `options`, `suggested_questions`, `conversation_id`, `status`.

JSON crudo: `backups/8447_pre_foundry_redis_20260921_194845/manifest/BASELINE_HTTP.json`

---

## 2. Suite unitaria local (pre-migración)

Ejecutar antes y después de cambios:

```powershell
cd c:\NovusIntelligence\BancoSantaCruz\BancaConversacional
.\.venv\Scripts\python.exe -m pytest tests/unit/test_context_load.py tests/unit/test_redis_session_store.py tests/unit/test_core_portfolio_mapper.py -q
```

**Estado post-implementación servicios (2026-09-21):** 6 passed en  
`test_context_persistence_service`, `test_product_context_service`, `test_product_context_tools`  
(+ `test_context_load` sin regresión en corrida previa: 13 passed total con context_load).

---

## 3. Capacidades que NO deben degradarse

Prioridad alta (guía + fixes previos):

- Lista de productos: «lista mis productos», «cuáles son mis productos», typos
- Saldos: actual / disponible (cuentas y TC)
- Préstamos y cuentas (selección, campos, continuidad)
- Correcciones y comparaciones
- FAQ / preguntas institucionales
- `context_info` → `CONTEXT_LOADED` / `CONTEXT_REFRESHED` con CAS y `SESSION_BUSY` bajo contención

---

## 4. Contrato WRITE PATH (orquestador)

- `POST /turn` con `context_info=true`, `question=null`, `context.data` obligatorio
- Persistencia: REPLACE snapshot completo + `expected_revision` (CAS)
- Locks: `ConversationGate` en carga de contexto

---

## 5. Criterios de aceptación post-migración

| Check | Baseline |
|-------|----------|
| `/health` | Igual o mejor |
| `/ready/redis` | `ok=true` |
| Smoke `/turn` institucional | 200 + contrato válido |
| `/turn` context_info | 200 CONTEXT_* o 503 SESSION_BUSY (no 500) |
| Suite unitaria context+redis | 100% pass |
| Flag `GENESIS_FOUNDRY_PRODUCT_TOOLS=0` | Comportamiento idéntico a este baseline |

---

## 6. Notas

- El orquestador .NET no forma parte de este baseline HTTP directo; validar carga inicial en entorno integrado cuando haya VPN/credenciales.
- `/ready` genérico ausente: no usar como criterio de rollback hasta que se implemente explícitamente.
