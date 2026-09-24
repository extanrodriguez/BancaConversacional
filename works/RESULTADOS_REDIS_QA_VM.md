# Resultados Redis/Entra + V4 Azure desde VM QA

Fecha: 2026-09-18. Host: `vm-test002-genesis` (`20.127.25.24`). Servicio: `genesis-cognitive-8447` → `http://127.0.0.1:8447`.  
Código desplegado: paquete corp 8447 (SHA256 `f81d347a…`) + parche async Entra en `contract_inspector_app.py`.  
Cliente bancario de lectura: **726588** únicamente. Sin transacciones, sin PROD, sin otros clientes.

---

## 1. Redis / Entra / red privada

| Comprobación | Resultado |
|---|---|
| VM | `vm-test002-genesis` — OK |
| Identidad administrada (IMDS) | OID `c0784572-03ae-4314-9ad0-311b1fafb710` (system-assigned VM) — OK |
| Token scope Redis | Longitud ~1570 — OK (no se imprime token) |
| Autorización data-plane Entra | `ENTRA_PING True` con username=OID — **ya autorizada** |
| DNS privado | `bsc-cognitive-redis-qa.eastus.redis.azure.net` → `192.168.150.7` (privatelink) — OK |
| TCP `:10000` | OK |
| Config efectiva servicio | `GENESIS_ENV=qa`, `GENESIS_SESSION_BACKEND=redis`, `GENESIS_REDIS_REQUIRED=1`, `GENESIS_REDIS_AUTH_MODE=entra_managed_identity`, URLs `rediss://…:10000/0`, `GENESIS_SEMANTIC_MODE=azure_plan` |
| Backup env | `/opt/genesis-cognitive-8447/Genesis_v2/.env.bak.entra.v4.20260918_105950` |
| Dependencias venv servicio | `redis 8.1.0`, `redis-entraid` import OK, fábrica + V4 markers presentes |
| `GET /ready/redis` | **HTTP 200** — `session_backend=redis`, `lock_backend=redis`, `session_ping=true`, `lock_ping=true`, `auth_mode=entra_managed_identity`, `errors=[]` |
| `redis_entra_ops_probe.py --cas --lock` | **ok=true** — `session_ping`, `lock_ping`, `set_get_del`, `lock_nx`, `cas_conflict` |
| Concurrencia HTTP 2 procesos | Role A: HTTP 200 `VALID_CONTRACT`; Role B: HTTP 200 `NON_OPERATIONAL` (solape real, conversación sintética `redis-harness-shared`, customer `SYN-REDIS`) — exit 0 ambos |

### Bloqueo encontrado y corrección

Tras cablear Entra, `create_and_ping` / `get_conversation_gate()` **hacen deadlock** si se ejecutan en el hilo del event loop de uvicorn (IMDS/redis-entraid sync). Evidencia: timeout 15s dentro de `asyncio.run`; OK en 0.38s vía `asyncio.to_thread`.  
Mitigación aplicada en QA: precalentar el gate en `create_app` (antes del loop) + `/ready/redis` vía `asyncio.to_thread`. Sin este parche no se declara readiness remoto.

### No ejecutado (Redis)

- Renovación sostenida de token Entra a lo largo de TTL largo.
- Política de clúster Non-Clustered en portal Azure (no verificada vía ARM en esta corrida; WATCH/MULTI CAS funcionó en probe).

---

## 2. Interpretación Azure (V4)

Entorno modelo en arranque del servicio: provider `AZURE_OPENAI`, deployment `gpt-4o-mini`, framework Agent Framework.  
Flag: `GENESIS_SEMANTIC_MODE=azure_plan`. Contexto 726588: `CONTEXT_LOADED`, **`context_source=lab_fallback`**, `products_count=4`, `active_count=3`, `has_core_error=true` (Core remoto con error; lab fallback autorizado).

Resumen corrida (`works/_qa_v4_azure_726588_raw.json`):

| Métrica | Valor |
|---|---|
| Turnos | 13 |
| HTTP 200 | 13 |
| Turnos con `audit.semantic_mode=azure_plan` | 5 |
| Turnos con llamada real a modelo (`inference_count≥1` o evidencia proposer/verifier) | 5 |
| Suma `inference_count` | 10 |

### Llamadas reales al modelo (evidencia)

| Journey / turno | Pregunta (sanitizada) | Evidencia |
|---|---|---|
| A1 | ¿Con cuánto puedo contar? | `inference_count=2`, `slowest_step=verifier`, ~42s |
| B1 | ¿Cuál es el saldo de mi cuenta? | `semantic_mode=azure_plan`, `brain_source=resolve_full`, calls proposer+verifier (`gpt-4o-mini`), `task_statuses.t1.balance=available` |
| C1 | ¿Cuál es el saldo disponible de mi cuenta? | `azure_plan` + proposer/verifier, `t1.available=available` |
| C2 | Dime la visión del banco | `azure_plan` + proposer/verifier, `rag_status=FAQ` |
| E1 | ¿Cuál es el saldo de mi cuenta de ahorro? | `azure_plan` + proposer/verifier |

### Atajos / sin modelo (esperado o parcial)

| Turno | Ruta | Nota |
|---|---|---|
| A2 «la de dólares» | `field_fastpath_currency_switch` | Sin USD en portafolio → «no encuentro producto…» (**NO APLICA USD** en 726588) |
| B2 «saldo contable» | `field_fastpath_balance` | No re-invocó modelo; respondió saldo actual (no ausencia ledger explícita) |
| C3 «volvamos a esa cuenta» | `field_fastpath_pending_continuity` | Retomó cuenta ahorros |
| D1 tasa+definición | `field_fastpath_mixed_pk` | Pedió selección de préstamo; **no** pasó por `azure_plan` |
| D2 selección | `t2_shortcut` | Detalle préstamo (tasa) sin glosario «qué significa» |
| F1 mixtas | `field_fastpath_personal_rate` | Solo selección préstamo; **perdió** el pendiente de saldo cuenta |
| F2 | `t2_shortcut` | Completó préstamo |

### Fallo Azure plan

| Turno | Resultado |
|---|---|
| E2 «No, la corriente; además dime la misión» | `status=PROVIDER_ERROR`, `intent=SEMANTIC_AZURE_PLAN_FAILED`, `error_class=InvalidModelOutputError`, `degraded=true`, **sin** fallback heurístico |

---

## 3. Recuperación de conocimiento

| Caso | Resultado |
|---|---|
| Visión del banco (C2) | **OK** — texto institucional recuperado; `rag_status=FAQ` bajo ruta `azure_plan` |
| Misión (E2, junto a corrección) | **No recuperada** — falló interpretación Azure (`InvalidModelOutputError`) antes de KB |
| Definición de «tasa» (D) | **No ejecutada como KB** — atajo personal devolvió ficha préstamo sin faceta glosario |
| Foundry index / corpus | **No modificado** (fuera de alcance) |

---

## 4. Respuesta final (comportamiento observado)

| Journey | Veredicto corto |
|---|---|
| A disponible→USD | Disponible DOP respondido; USD correctamente ausente (no inventa producto) |
| B saldo→contable | Saldo respondido; «contable» no diferenció ledger ausente |
| C visión→retomar | Visión OK; retorno a cuenta OK vía continuidad |
| D tasa+definición | Selección OK; definición/significado **no** cubierto en la respuesta |
| E corrección+misión | Ahorro OK; corrección+misión **falla** Azure plan |
| F dos pendientes | Completó préstamo; **no** conservó pendiente de saldo cuenta |

Respuestas finales incluyen saludo/nombre de lab y montos (saneados en raw). Origen de datos personales: **lab_fallback**, no Core vivo.

---

## 5. Casos / comprobaciones no ejecutadas

- Transacciones bancarias  
- Otros clientes ≠ 726588  
- Cambio orquestador externo / índices Foundry  
- USD / tarjetas / DAP / certificados reales (no en portafolio 726588)  
- Renovación sostenida token Entra  
- PROD  
- Matriz 236+24 completa  

---

## 6. Conclusión por carril

| Carril | ¿Éxito remoto? |
|---|---|
| **Redis/Entra** | **Sí** — MI, PE/DNS, data-plane, `/ready/redis`, probe CAS+lock, solape HTTP 2 procesos |
| **Interpretación Azure V4** | **Parcial** — varias rutas `azure_plan` con proposer/verifier reales; atajos aún capturan mixtas; E2 falla `InvalidModelOutputError` |
| **Conocimiento** | **Parcial** — visión FAQ OK; misión/definición no acreditadas en esta corrida |
| **Respuesta final** | **Parcial** — lecturas simples OK; multi-intención/corrección+institucional incompletas |

Artefactos: `works/_qa_v4_azure_726588_raw.json`, runner `works/_qa_v4_azure_run_726588.py`, scripts remoto en `deploy/corp-8447/_remote_*`.
