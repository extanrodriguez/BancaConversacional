# Redis Azure QA — cableado en host :8447

Fecha verificación: **2026-09-19**. Recurso: `bsc-cognitive-redis-qa` (Azure Managed Redis, East US).

## Estado actual (vigente)

| Campo | Valor |
|---|---|
| Host cognitivo | `vm-test002-genesis` / `20.127.25.24:8447` |
| Endpoint Redis | `bsc-cognitive-redis-qa.eastus.redis.azure.net:10000` |
| DNS privado | `192.168.150.7` (privatelink) |
| TLS | Obligatorio (`rediss://`) |
| Red | Public access **disabled**; Private Endpoint |
| Access Keys | **Deshabilitadas** en el recurso |
| Auth efectiva | `GENESIS_REDIS_AUTH_MODE=entra_managed_identity` |
| Variables | `GENESIS_REDIS_URL`, `GENESIS_CONV_LOCK_REDIS_URL` (endpoint **sin** password embebido) |
| `.env` remoto | `/opt/genesis-cognitive-8447/Genesis_v2/.env` (modo `600`) |
| Backup plan 2026-09-19 | `.env.bak.redis.plan.20260919_085524` |

Detalle Entra (fábrica, MI, probes): [`CONEXION_REDIS_QA_ENTRA.md`](CONEXION_REDIS_QA_ENTRA.md).  
Evidencia VM: [`RESULTADOS_REDIS_QA_VM.md`](RESULTADOS_REDIS_QA_VM.md).  
Estado wire: [`REDIS_QA_WIRE_STATUS.md`](REDIS_QA_WIRE_STATUS.md).

## Checklist verificado 2026-09-19

1. SSH al host QA (`20.127.25.24`) — OK  
2. Backup `.env` — OK  
3. URLs presentes (`rediss://…:10000/0`) + `SESSION_BACKEND=redis` + `REDIS_REQUIRED=1` + Entra — OK  
4. TCP/DNS Private Endpoint — OK  
5. `systemctl restart genesis-cognitive-8447` → `active` — OK  
6. `GET /health` → `ok` — OK  
7. `GET /ready/redis` → `ok=true`, `session_ping=true`, `lock_ping=true` — OK  
8. `redis_entra_ops_probe.py --cas --lock` (con `.env` del servicio) → `ok True` — OK  
9. Dos turnos misma `conversation_id` (lab 726588) → ambos `VALID_CONTRACT` — OK  

## Access Key (plan original — no aplicable hoy)

El plan inicial asumía Primary access key:

```text
rediss://:<ACCESS_KEY>@bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0
```

**No usar** mientras Access Keys estén deshabilitadas. El script legado `deploy/corp-8447/configure_redis_qa_8447.py` queda solo para el caso en que Azure vuelva a habilitar keys.

Si en el portal se reactivan Access Keys:

1. Obtener Primary key en **Authentication → Access keys** (no pegar en chat/git).  
2. `$env:AZURE_REDIS_ACCESS_KEY=…` + `$env:SSH_DEPLOY_PASS=…`  
3. `.\.venv\Scripts\python.exe .\deploy\corp-8447\configure_redis_qa_8447.py`  
4. Ajustar `GENESIS_REDIS_AUTH_MODE=url` si el servicio deja de usar Entra.

## Variables Entra (referencia sin secretos)

Ver `deploy/corp-8447/redis_qa.env.example`. Resumen:

```text
GENESIS_SESSION_BACKEND=redis
GENESIS_REDIS_REQUIRED=1
GENESIS_REDIS_AUTH_MODE=entra_managed_identity
GENESIS_REDIS_URL=rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0
GENESIS_CONV_LOCK_REDIS_URL=rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0
```

## Relación con prueba multiproceso 1C

Store Redis real en QA habilitado. Matriz de concurrencia: [`REDIS_CONCURRENCY_PROCEDURE_1C.md`](REDIS_CONCURRENCY_PROCEDURE_1C.md) (harness HTTP **desde el host**, no desde PC sin PE).
