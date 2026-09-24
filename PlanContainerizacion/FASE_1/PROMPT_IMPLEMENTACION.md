# Fase 1 — Prompt de implementación para Cursor

> **Instrucción:** Copia el bloque completo entre `--- INICIO PROMPT ---` y `--- FIN PROMPT ---` en un chat nuevo de Cursor (modo Agent). No modifiques el prompt salvo valores de entorno específicos de tu máquina.

---

## --- INICIO PROMPT ---

Implementa la **Fase 1 de containerización** del proyecto Genesis Cognitive (Banca Conversacional Banco Santa Cruz).

### Contexto del proyecto

- **Repo:** `c:\NovusIntelligence\BancoSantaCruz\BancaConversacional`
- **Stack:** Python 3.12, FastAPI, uvicorn, Azure OpenAI, Azure AI Search
- **Entry point:** `scripts/run_contract_inspector.py`
- **App:** `src/genesis_cognitive/demo/contract_inspector_app.py`
- **Estado actual:** `ReactiveSessionStore` in-memory en `src/genesis_cognitive/context/reactive_store.py`
- **Deploy actual:** VM con systemd en puerto 8446 (`deploy/corp-8446/`)
- **Plan de referencia:** lee `PlanContainerizacion/FASE_1/README.md`, `00_ARQUITECTURA_OBJETIVO.md`, `VARIABLES_ENTORNO.md`

### Objetivo de esta fase

1. Dockerizar la API con imagen reproducible.
2. Externalizar sesiones y snapshots a **Redis** (obligatorio para N réplicas).
3. Mantener fallback in-memory solo si `GENESIS_REDIS_URL` está vacío (dev sin compose).
4. CI: build imagen + pytest + smoke.
5. Documentar deploy en VM con docker compose (paralelo a 8446, sin apagar systemd).

### Tareas concretas (implementar en este orden)

#### T1 — Dependencias

- Añadir `redis>=5.0.0` a `requirements.runtime.txt` y `pyproject.toml`.
- Verificar que `pip install -e ".[dev]"` sigue funcionando.

#### T2 — RedisSessionStore

Crear `src/genesis_cognitive/context/redis_session_store.py`:

- Implementar la **misma interfaz pública** que `ReactiveSessionStore`:
  - `get_session(conversation_id) -> SessionState | None`
  - `put_session(conversation_id, session) -> None`
  - `create_session(conversation_id, customer_id) -> SessionState`
  - `delete_session(conversation_id) -> None`
  - `get_snapshot(customer_id) -> CustomerContextSnapshot | None`
  - `get_snapshot_age(customer_id) -> float | None`
  - `put_snapshot(customer_id, snapshot) -> None`
  - `session_count()`, `snapshot_count()`, `session_keys()` (diagnóstico)
- Claves Redis:
  - `session:{conversation_id}` → JSON serializado de SessionState
  - `customer:{customer_id}:snapshot` → JSON de CustomerContextSnapshot + metadata
- TTL: usar `SETEX` / `expire` con `GENESIS_SESSION_TTL_S` (default 1800) y `GENESIS_SNAPSHOT_TTL_S` (default 600).
- Serialización: `dataclasses.asdict` + JSON; para `CustomerContextSnapshot` usar métodos existentes o `model_dump`/`model_validate` si es Pydantic.
- Pool de conexiones con `redis.from_url(GENESIS_REDIS_URL, decode_responses=True)`.
- Manejo de errores: log warning si Redis cae; no crashear el worker en get (retornar None).

#### T3 — Factory

Crear `src/genesis_cognitive/context/session_store_factory.py`:

```python
def create_session_store() -> ReactiveSessionStore | RedisSessionStore:
    url = os.getenv("GENESIS_REDIS_URL", "").strip()
    if url:
        return RedisSessionStore(url, ...)
    return ReactiveSessionStore(...)
```

#### T4 — Integración en contract_inspector_app

- Buscar dónde se instancia `ReactiveSessionStore()` (singleton o global).
- Reemplazar por `create_session_store()`.
- No cambiar lógica de negocio ni guardrails.

#### T5 — Docker

Copiar/adaptar a la **raíz del repo**:

- `Dockerfile` (desde `PlanContainerizacion/FASE_1/Dockerfile`)
- `.dockerignore` (desde `PlanContainerizacion/FASE_1/.dockerignore`)
- `docker-compose.yml` (desde `PlanContainerizacion/FASE_1/docker-compose.yml` o symlink)

Verificar:

```powershell
docker build -t genesis-api:local .
docker compose up -d
curl http://127.0.0.1:8445/health
```

#### T6 — Tests

- Unit test `tests/unit/test_redis_session_store.py`:
  - Usar `fakeredis` o skip si no hay Redis (`pytest.importorskip`).
  - Probar put/get session, TTL expiry (mock time o TTL corto), put/get snapshot.
- Test factory: con env vacío → in-memory; con URL fakeredis → Redis store.

#### T7 — CI

Crear `.github/workflows/build-test.yml`:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports: [6379:6379]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -e ".[dev]" fakeredis
      - run: pytest tests/unit -q
      - run: docker build -t genesis-api:ci .
```

Secrets en GitHub: NO commitear keys; CI solo corre tests unitarios sin OpenAI real (mock o skip smoke).

#### T8 — Smoke contra contenedor

- Asegurar `Test_local/run_mvp.py` acepta `--endpoint` o respeta `GENESIS_ENDPOINT`.
- Documentar en FASE_1/README.md el comando post-compose.

#### T9 — Deploy script VM

Crear `deploy/docker/deploy_compose.sh`:

- Pull/build imagen
- `docker compose up -d --remove-orphans`
- Curl health
- NO tocar `genesis-cognitive-8446.service`

### Restricciones

- **NO** hacer commit de `.env`, API keys, ni passwords.
- **NO** desplegar a Azure (eso es Fase 2).
- **NO** apagar systemd 8446.
- **NO** cambiar puerto por defecto fuera del rango 8440–8449 (nunca 8443).
- Minimizar diff: no refactorizar guardrails ni LLM pipeline.
- Responder en español en comentarios de commit si el usuario pide commit.

### Criterios de aceptación (debes verificar antes de terminar)

1. `pytest tests/unit -q` → todo verde
2. `docker compose up` → `/health` 200
3. UI `/pruebas` carga con `GENESIS_SERVE_UI=true`
4. Dos réplicas (`api` + `api-replica` con profile scale-test) comparten sesión:
   - Turn 1 POST `/turn` en 8445
   - Turn 2 follow-up en 8448 misma `conversation_id` → mantiene contexto
5. Sin `GENESIS_REDIS_URL` local sigue funcionando con in-memory (start_local.ps1)
6. Imagen no incluye `.venv` ni secretos

### Archivos de referencia existentes

- `PlanContainerizacion/FASE_1/Dockerfile`
- `PlanContainerizacion/FASE_1/docker-compose.yml`
- `PlanContainerizacion/FASE_1/.env.example`
- `src/genesis_cognitive/context/reactive_store.py` (interfaz a replicar)
- `deploy/corp-8446/deploy_8446.sh` (patrón deploy, no modificar)

### Entregable final

Al terminar, resume:

- Archivos creados/modificados
- Comandos para build, run, test
- Resultado smoke
- Pendientes para Fase 2

## --- FIN PROMPT ---
