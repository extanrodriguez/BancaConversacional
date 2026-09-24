# ESTADO PRE-MIGRACIÓN — Capa cognitiva :8447

**Fecha/hora inventario:** 2026-09-21 19:48–19:50 (hora local Windows)  
**Alcance:** solo lectura. No se detuvo ni modificó el servicio productivo.

---

## 1. Runtime remoto (QA)

| Campo | Valor |
|--------|--------|
| Host | `vm-test002-genesis` / `20.127.25.24` |
| Puerto | `8447` |
| Servicio systemd | `genesis-cognitive-8447.service` |
| Usuario servicio | `genesis` |
| WorkingDirectory | `/opt/genesis-cognitive-8447/Genesis_v2` |
| ExecStart | `/opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python scripts/run_contract_inspector.py` |
| EnvironmentFile | `/opt/genesis-cognitive-8447/Genesis_v2/.env` (modo `600`) |
| Unit local (espejo) | `deploy/corp-8447/genesis-cognitive-8447.service` |
| PID local Windows | **N/A** — `:8447` no escucha en este PC |
| SSH desde esta sesión | Credenciales **no** presentes en env (`SSH_DEPLOY_PASS` unset) |

Health remoto observado:

```json
{"status":"ok","service":"genesis-cognitive","env":"qa","version":"0.8.0","rag":"ready"}
```

Redis readiness:

```json
{"ok":true,"session_backend":"redis","lock_backend":"redis","auth_mode":"entra_managed_identity","redis_required":true,"session_ping":true,"lock_ping":true,"session_host":"bsc-cognitive-redis-qa.eastus.redis.azure.net","lock_host":"bsc-cognitive-redis-qa.eastus.redis.azure.net","errors":[]}
```

---

## 2. Git / workspace local

| Campo | Valor |
|--------|--------|
| Raíz workspace | `c:\NovusIntelligence\BancoSantaCruz\BancaConversacional` |
| `.git` en raíz | **No existe** |
| Commit / branch | **N/A** (copia de trabajo sin repositorio git en raíz) |
| Python local | 3.12.8 (sistema + `.venv`) |
| Paquete | `genesis-cognitive` (`pyproject.toml` version proyecto `0.1.0`; runtime QA reporta `0.8.0`) |

> Nota: el backup de código se hizo desde el workspace local (fuente de deploy). El árbol vivo de la VM no se copió por falta de SSH en la sesión.

---

## 3. Código y entrypoints

| Rol | Ruta |
|-----|------|
| App FastAPI | `src/genesis_cognitive/demo/contract_inspector_app.py` |
| Entry | `scripts/run_contract_inspector.py` |
| Session + CAS | `src/genesis_cognitive/context/redis_session_store.py` |
| Locks | `src/genesis_cognitive/context/conversation_gate.py` |
| Cliente Redis / Entra | `src/genesis_cognitive/context/redis_client_factory.py` |
| Mapper contexto Core | `src/genesis_cognitive/context/core_portfolio_mapper.py` |
| Snapshot tipado | `src/genesis_cognitive/context/customer_context_snapshot.py` |
| Foundry KB (conocimiento) | `src/genesis_cognitive/rag/foundry_kb_agent.py` |
| Azure brain / plan | `src/genesis_cognitive/brain/` |
| Agent Framework | `src/genesis_cognitive/agents/agent_framework_turn_resolver.py` |

**No existen** clases con nombres `ContextPersistenceService`, `ProductContextService` ni tool `get_customer_products`.  
Equivalentes actuales: `_persist_core_context()` + `RedisSessionStore` + lectura de `session.snapshot`.

---

## 4. Endpoints relevantes

| Método | Path | Estado observado |
|--------|------|------------------|
| GET | `/health` | OK |
| GET | `/ready` | **404** (no implementado) |
| GET | `/ready/redis` | OK (`ok=true`) |
| POST | `/turn` | OK (contrato orquestador) |
| GET | `/pruebas/` | OK 200 |
| POST | `/inspect` | Lab/debug (no sustituye `/turn`) |
| POST | `/chat/front` | Alias APK de `/turn` |

---

## 5. Contrato `/turn` (orquestador)

`TurnRequest` (Pydantic, `extra="ignore"`):

- `question`, `selected_option_ref`
- `conversation_id`, `customer_id`, `client_id`
- `top_k`, `force_core_query`
- `context_info`, `context_op` (`load` \| `refresh`)
- `context` → exige `context.data` cuando `context_info=true`

**WRITE PATH actual (ya existe):**

```text
Orquestador → POST /turn context_info=true
  → ConversationGate (lock)
  → map_core_portfolio(context.data)
  → store.put_session(..., expected_revision=CAS)
  → Redis session:{conversation_id} (+ customer:{id}:snapshot)
  → CONTEXT_LOADED | CONTEXT_REFRESHED
```

**READ PATH actual (turno NL):**

```text
POST /turn question=...
  → inspect() pipeline (FAQ / Foundry KB / Azure brain / snapshot Redis)
  → app_channel + core_channel + audit
```

Estrategia de escritura observada: **REPLACE del snapshot completo** de la sesión en cada `context_info` (no PATCH parcial). CAS vía `expected_revision`.

---

## 6. Redis

| Campo | Valor |
|--------|--------|
| Recurso | `bsc-cognitive-redis-qa` (Azure Managed Redis) |
| Auth | Microsoft Entra ID + Managed Identity (`redis-entraid`) |
| Access Keys | Deshabilitadas |
| Fail-closed | `GENESIS_REDIS_REQUIRED=1` (según docs QA) |
| Keys | `session:{conversation_id}`, `customer:{id}:snapshot`, `genesis:conv_lock:{conversation_id}` |
| TTL sesión | `GENESIS_SESSION_TTL_S` default 1800; snapshot atado a sesión |

Doc: `works/REDIS_QA_AZURE_8447.md`

---

## 7. Microsoft Foundry / Azure OpenAI / RAG

| Pieza | Uso actual |
|--------|------------|
| Foundry KB Agent | Conocimiento institucional (FAQ/RAG). **No** saldos/productos personales |
| Azure AI Search | Índice `bsc-kb-conocimiento` (deploy) |
| Azure Intent Brain / Draft | Intención y redacción sobre hechos ya verificados |
| Agent Framework | Salida estructurada JSON (no registry amplio de tools bancarias) |

Principio documentado vigente (`docs/architecture/ESTRATEGIA_FOUNDRY_COGNITIVA.md`):

> Personal → Cognitiva + snapshot Redis. Foundry no interviene en saldos.

---

## 8. Taxonomía real de productos (interna)

| Core | `product_type` interno |
|------|-------------------------|
| CA | SAVINGS (o CHECKING/PAYROLL por descripción) |
| CC | CHECKING |
| TC | CREDIT_CARD |
| PR | LOAN |
| CD / DAP / DP | TERM_DEPOSIT |

Enums del prompt (`ACCOUNT`, `DEPOSIT`) deben mapearse a esta taxonomía; **no inventar** categorías nuevas.

---

## 9. Configuración (sin secretos)

Espejos versionados:

- `deploy/corp-8447/.env.example`
- `deploy/corp-8447/redis_qa.env.example`
- `.env.example` (dev local)

Secretos solo en host `.env` / Key Vault / MI. Inventario de nombres:  
`backups/8447_pre_foundry_redis_20260921_194845/config/SECRETS_INVENTORY.md`

---

## 10. Tests y guía conversacional

- Unitarios: `tests/unit/` (Redis, Foundry KB, context, cognitive…)
- Validación remota: `Test_local/validate_*8447*.py`
- Guía funcional: `works/validacion_guia_fix/Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.MD`  
  (no se encontró el zip `paquete(6)` con ese nombre exacto; hay MD/HTML equivalentes)

---

## 11. Backup creado

| Campo | Valor |
|--------|--------|
| Ubicación | `backups/8447_pre_foundry_redis_20260921_194845/` |
| Manifest | `BACKUP_MANIFEST.md` |
| Checksums | `BACKUP_CHECKSUMS.txt` (SHA256) |
| Archivos | 468 |
| Bytes | ~6.3 MB |
| Verificación críticos | OK (`manifest/CRITICAL_VERIFY.json`) |

---

## 12. Gap vs arquitectura objetivo del prompt

Ya existe y está probado:

- Persistencia de contexto del orquestador → Redis
- CAS / locks / fail-closed / Entra MI
- Separación conocimiento (Foundry KB) vs personal (snapshot)

**Pendiente respecto al prompt maestro:**

1. Nombrar/extraer `ContextPersistenceService` y `ProductContextService` (READ path tipado)
2. Capability `get_customer_products` consumible por Foundry **sin** que el LLM elija `customer_id`
3. Integrar Foundry Agent con tool calling sobre productos (hoy Foundry es KB; personal va por pipeline cognitivo)
4. Endpoint `/ready` genérico (hoy solo `/ready/redis`)
5. Pruebas de aislamiento sesión A ≠ cliente B para la nueva tool

**Riesgo principal:** cambiar el path personal a Foundry+tools sin feature flag puede regresar capacidades ya estabilizadas (lista productos, saldos, continuidad, FAQ).
