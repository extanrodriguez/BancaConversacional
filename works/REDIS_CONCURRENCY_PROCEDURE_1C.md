"""Procedimiento reproducible: Redis local aislado + 2 procesos cognitivos HTTP.

Para Redis Azure Managed en QA `:8447` (Private Endpoint + TLS + Entra MI), ver
[`REDIS_QA_AZURE_8447.md`](REDIS_QA_AZURE_8447.md) (checklist 2026-09-19: `/ready/redis` OK)
y [`CONEXION_REDIS_QA_ENTRA.md`](CONEXION_REDIS_QA_ENTRA.md).
Access Keys deshabilitadas → no usar `configure_redis_qa_8447.py` salvo que Azure
vuelva a habilitar keys.

PENDIENTE en esta máquina (Docker local): Docker Desktop no tenía el engine activo
(`dockerDesktopLinuxEngine` pipe ausente). No se atribuye éxito Redis local.

## Requisitos
- Docker Desktop arrancado (o Redis local en puerto libre)
- Python venv del repo
- Puerto host 16379 libre (no usar Redis del banco ni credenciales ZIP)

## Arranque Redis de prueba

```powershell
docker rm -f genesis-1c-redis 2>$null
docker run -d --name genesis-1c-redis -p 16379:6379 redis:7-alpine
docker exec genesis-1c-redis redis-cli ping
# esperado: PONG
```

## Variables (ambos procesos)

```powershell
$env:GENESIS_REDIS_URL = "redis://127.0.0.1:16379/0"
$env:GENESIS_CONV_LOCK_REDIS_URL = "redis://127.0.0.1:16379/0"
$env:GENESIS_AZURE_BRAIN = "0"
```

## Barreras de solape (HTTP /turn, no WATCH directo)

Ejecutar en dos shells el script de prueba del repo:

```powershell
.\.venv\Scripts\python.exe tests/manual/redis_http_concurrency_harness.py --role A --barrier-dir $env:TEMP\genesis-1c-barrier
.\.venv\Scripts\python.exe tests/manual/redis_http_concurrency_harness.py --role B --barrier-dir $env:TEMP\genesis-1c-barrier
```

Casos cubiertos por el harness:
1. Dos turnos misma conversación (barrier antes de POST /turn)
2. Creación concurrente misma sesión
3. Dos sesiones mismo cliente
4. Clientes distintos
5. Expiración TTL durante procesamiento (session_ttl corto)
6. Escritura snapshot asociado (context_info=true)

Criterio de éxito consumidor:
- HTTP 200 siempre hacia NvidiaChatClient
- Nunca HTTP 409
- `client_response` string no nulo
- En solape: serialización (ambos VALID_*) o un `SESSION_BUSY` sin saldo inventado
- Estado final Redis coherente (una revisión monotónica por conversation_id)

## Limpieza

```powershell
docker rm -f genesis-1c-redis
```
