# Conexión Redis QA — Microsoft Entra

Fecha: 2026-09-18.

## Resumen

La capa cognitiva usa una **fábrica común** de clientes Redis para **sesiones** (`RedisSessionStore`) y **candados** (`ConversationGate`), con modo `GENESIS_REDIS_AUTH_MODE=entra_managed_identity` (redis-entraid + identidad administrada). Access Keys permanecen deshabilitadas en el recurso QA.

Conserva la corrección cognitiva V3.1 (plan multi-tarea, CAS, serialización `pending_tasks` / `compare_set` / `catalog_personal_map`, contratos `/turn`).

## Diff principal

| Archivo | Cambio |
|---|---|
| `src/genesis_cognitive/context/redis_client_factory.py` | **Nuevo.** Endpoint sin secretos, Entra MI / URL, `diagnose_redis_backends`, fail helpers |
| `src/genesis_cognitive/context/redis_session_store.py` | Cliente vía fábrica; fail-closed si URL rota; `catalog_personal_map` en serialización |
| `src/genesis_cognitive/context/conversation_gate.py` | Candado vía misma fábrica; exige URL si perfil Redis |
| `src/genesis_cognitive/demo/contract_inspector_app.py` | `GET /ready/redis` (no altera `/turn` ni `/health`) |
| `pyproject.toml` | `redis==8.1.0`, `redis-entraid==1.2.1` |
| `deploy/corp-8447/redis_qa.env.example` | Variables QA Entra (sin secretos) |
| `scripts/redis_entra_ops_probe.py` | PING / KV / opcional CAS+lock con la fábrica real |
| `tests/unit/test_redis_entra_factory.py` | Unitarios Entra mock + fail-closed |

### Variables nuevas vs existentes

| Variable | Estado | Uso |
|---|---|---|
| `GENESIS_REDIS_AUTH_MODE` | **Nueva** | `entra_managed_identity` \| `url` |
| `GENESIS_SESSION_BACKEND` | **Nueva** | `redis` \| `memory` \| `auto` |
| `GENESIS_REDIS_REQUIRED` | **Nueva** | `1` fuerza Redis aunque `GENESIS_ENV=dev` |
| `GENESIS_REDIS_MANAGED_IDENTITY_TYPE` | **Nueva** | `system_assigned` (default) \| `user_assigned` |
| `GENESIS_REDIS_MANAGED_IDENTITY_CLIENT_ID` | **Nueva** | Client ID si UAI |
| `GENESIS_REDIS_ENTRA_RESOURCE` | **Nueva** | Default `https://redis.azure.com/` |
| `GENESIS_REDIS_URL` | Existente | Endpoint/DB **sin** password en modo Entra |
| `GENESIS_CONV_LOCK_REDIS_URL` | Existente | Candados (fallback a `GENESIS_REDIS_URL`) |
| `GENESIS_SESSION_TTL_S` | Existente | Default 1800 (TTL sesión, no frescura de saldo) |
| `GENESIS_CONV_LOCK_TTL_S` | Existente | TTL candado |

## Recurso e identidad (sin secretos)

| Propiedad | Valor |
|---|---|
| Recurso | `bsc-cognitive-redis-qa` |
| Host | `bsc-cognitive-redis-qa.eastus.redis.azure.net` |
| Puerto | `10000` |
| TLS | Obligatorio (`rediss://`) |
| Access Keys | Deshabilitadas |
| Auth | Microsoft Entra |
| Identidad prevista | System-assigned de la VM cognitiva (`vm-test002-genesis` por historial; **verificar en Azure**) |
| Política de clúster | Debe ser **Non-Clustered** (código usa `WATCH/MULTI` vía `redis.Redis`, no `RedisCluster`) |
| Expulsión recomendada | `noeviction` |

Un `PING` no valida transacciones ni la política de clúster.

## Mecanismo de configuración del servicio

Host QA histórico: proceso **systemd** `genesis-cognitive-8447`, `.env` en:

`/opt/genesis-cognitive-8447/Genesis_v2/.env` (modo `600`)

Incorporar **solo** las variables de `deploy/corp-8447/redis_qa.env.example` (no reemplazar Foundry/Azure existentes).

Aplicar:

```bash
# En la VM (tras backup)
cp /opt/genesis-cognitive-8447/Genesis_v2/.env /opt/genesis-cognitive-8447/Genesis_v2/.env.bak.entra.$(date +%s)
# merge manual de redis_qa.env.example → .env
sudo systemctl restart genesis-cognitive-8447
curl -sS http://127.0.0.1:8447/ready/redis
```

Revertir: restaurar `.env.bak.entra.*` y `systemctl restart`.

Un `export` en consola **no** actualiza el proceso systemd. Un `.env` no se carga solo por existir: el unit debe referenciar `EnvironmentFile=`.

## Evidencia local (esta máquina)

| Prueba | Resultado |
|---|---|
| Unitarios fábrica Entra + fail-closed | **passed** (`test_redis_entra_factory.py`) |
| Regresión cognitiva V3.1 + Redis unit | **58 passed** (correccion/adicionales/cierre/entra) |
| Docker Redis local (KV/CAS/lock reales) | **No ejecutado** — Docker Desktop engine inactivo (`dockerDesktopLinuxEngine` ausente) |
| DNS / TLS / PING al PE QA desde esta PC | **No ejecutado** — sin ruta al private endpoint |
| Entra en VM + data-plane Redis | **Pendiente remoto** — requiere MI autorizada en Redis + reinicio controlado del servicio |
| Renovación de token sostenida | **No comprobada** en vivo (cubierta por redis-entraid; falta sesión larga en VM) |
| HTTP `/turn` multiproceso contra Redis QA | **Pendiente** (harness en `REDIS_CONCURRENCY_PROCEDURE_1C.md`) |

### Cómo se acredita que ambos usan Redis (cuando haya conectividad)

1. `GET /ready/redis` → `session_backend=redis`, `lock_backend=redis`, `session_ping=true`, `lock_ping=true`, `auth_mode=entra_managed_identity`.
2. `scripts/redis_entra_ops_probe.py --cas --lock` → mismos clientes de fábrica; CAS conflicto + SET NX.
3. Ausencia de fallback: con `GENESIS_ENV=qa` y URL vacía → arranque falla; con URL inalcanzable → falla (también en `dev`).

## Preparación Azure aún requerida (bloquea remoto)

1. Confirmar VM del proceso cognitivo e identidad system-assigned (o UAI + client id).
2. En Redis → Entra Authentication: agregar esa identidad; comprobar Object ID (el cliente bancario `726588` **no** es la identidad Redis).
3. Private endpoint aprobado + DNS de la VM → IP privada del PE.
4. Política Non-Clustered + `noeviction`.
5. Reinicio **solo** del servicio cognitivo QA tras merge de env.

## Criterio de aceptación

- Código y pruebas locales: **cumplido**.
- Conexión autenticada real a `bsc-cognitive-redis-qa` con evidencia de store+lock Redis: **pendiente de permisos/ruta en VM**.
- No se declara éxito remoto por mocks.

## Relación con documentos previos

- `works/REDIS_QA_WIRE_STATUS.md` — cableado por Access Key quedó obsoleto (keys deshabilitadas); este documento es la ruta Entra.
- `works/REDIS_QA_AZURE_8447.md` / `configure_redis_qa_8447.py` — actualizar operativamente a Entra (dejar de inyectar keys).
- `works/REDIS_CONCURRENCY_PROCEDURE_1C.md` — harness HTTP multiproceso; usar las vars Entra en la VM.
