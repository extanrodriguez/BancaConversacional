# Migración controlada — Foundry product tools + Redis :8447

## Estado actual (reanudación 2026-09-21)

### Completado (reanudación)

| Fase | Entregable |
|------|------------|
| 0 | Inventario + probes QA remotos |
| Documentación | `ESTADO_PRE_MIGRACION_8447.md`, `ROLLBACK_8447.md`, `BASELINE_8447_PRE_MIGRACION.md` |
| Backup | `backups/8447_pre_foundry_redis_20260921_194845/` + checksums |
| WRITE PATH | `ContextPersistenceService` — `_persist_core_context` delega sin cambiar contrato `/turn` |
| READ PATH | `ProductContextService` + `execute_get_customer_products` |
| Tool schema | `agents/product_context_tools.py` (`get_customer_products`) |
| Foundry personal | `agents/foundry_personal_agent.py` — tool loop Azure OpenAI + Redis vía servicio |
| Cableado | En `_inspect_unlocked` **antes** de azure_plan, solo si `GENESIS_FOUNDRY_PRODUCT_TOOLS=1` |
| `/ready` | Endpoint agregado (agrega readiness Redis + flag) |
| Seguridad | Identidad solo desde sesión Redis; hint distinto → `FORBIDDEN` |
| Flag | `GENESIS_FOUNDRY_PRODUCT_TOOLS=0` (default en `.env.example` y `deploy_8447.sh`) |
| Tests | 16 unitarios OK (context + product tools + foundry helpers) |
| Paquete deploy | `deploy/corp-8446/dist/genesis_corp_8446.zip` (SHA256 en build log) |

### Deploy QA

**Bloqueado en esta sesión:** no hay `SSH_DEPLOY_PASS` ni clave SSH (`Permission denied` a `20.127.25.24`).

Para desplegar:

```powershell
$env:SSH_DEPLOY_PASS = "<password>"
$env:SSH_HOST = "20.127.25.24"
$env:SSH_USER = "genesis"
.\.venv\Scripts\python.exe .\deploy\corp-8447\deploy_ssh_password.py
```

Post-deploy (flag sigue OFF → regresión = baseline):

```powershell
Invoke-WebRequest http://20.127.25.24:8447/health
Invoke-WebRequest http://20.127.25.24:8447/ready
Invoke-WebRequest http://20.127.25.24:8447/ready/redis
```

Para activar Foundry product tools **después** de validar baseline:

```bash
# en VM .env
GENESIS_FOUNDRY_PRODUCT_TOOLS=1
sudo systemctl restart genesis-cognitive-8447
```

Rollback inmediato: `GENESIS_FOUNDRY_PRODUCT_TOOLS=0` + restart (ver `ROLLBACK_8447.md`).

### Sin cambiar (a propósito)

- Orquestador, WebSocket, frontend
- Handler `/turn` (misma firma y flujos `context_info` / NL)
- Pipeline personal existente cuando flag=0
- Foundry KB (conocimiento) — separado de datos personales

### Pendiente

1. Deploy QA con `SSH_DEPLOY_PASS`
2. Smoke + regresión guía FIX con flag=0
3. Activar flag=1 en QA y comparar matriz P0
4. Opcional: agente Foundry nativo (AI Projects) en lugar de Azure OpenAI tool loop — misma tool server-side

## Diagrama objetivo (implementación)

```text
WRITE: Orquestador → /turn context_info → ContextPersistenceService → Redis
READ:  (flag OFF) inspect() → azure_plan / snapshot [productivo actual]
READ:  (flag ON)  Foundry personal agent → get_customer_products → ProductContextService → Redis
                 (fallo → fallthrough azure_plan)
```

## Archivos nuevos / tocados

- `src/genesis_cognitive/context/context_persistence_service.py`
- `src/genesis_cognitive/context/product_context_service.py`
- `src/genesis_cognitive/agents/product_context_tools.py`
- `src/genesis_cognitive/agents/foundry_personal_agent.py`
- `src/genesis_cognitive/demo/contract_inspector_app.py` (delegación + hook + `/ready`)
- `deploy/corp-8447/.env.example`, `deploy_8447.sh`
- `tests/unit/test_*context*`, `test_foundry_personal_agent.py`
