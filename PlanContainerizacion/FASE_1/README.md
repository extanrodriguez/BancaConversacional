# Fase 1 — Docker + Redis + VM (lab)

**Duración estimada:** 2–3 semanas  
**Objetivo:** Contenedorizar la API Genesis, externalizar sesiones a Redis y desplegar en la VM corporativa con `docker compose`, sin interrumpir el servicio systemd en 8446 hasta validación.

## Entregables

| # | Entregable | Ubicación |
|---|------------|-----------|
| 1 | Dockerfile multi-stage | `Dockerfile` (raíz repo) |
| 2 | docker-compose (api + redis) | `docker-compose.yml` |
| 3 | `.dockerignore` | raíz |
| 4 | `RedisSessionStore` | `src/genesis_cognitive/context/redis_session_store.py` |
| 5 | Factory de store por env | `src/genesis_cognitive/context/session_store_factory.py` |
| 6 | `redis` en requirements | `requirements.runtime.txt` |
| 7 | CI build + test | `.github/workflows/build-test.yml` |
| 8 | Script deploy VM | `deploy/docker/deploy_compose.sh` |
| 9 | Smoke contra contenedor | `Test_local/run_mvp.py --endpoint` |

## Arquitectura Fase 1

```text
VM vm-test002-genesis (192.168.150.5)
├── systemd genesis-cognitive-8446  (legacy, sigue activo)
└── docker compose (nuevo, puerto 8447 o 8445 interno)
      ├── genesis-api:8445
      └── redis:6379
```

## Pasos de implementación

### 1. Preparar imagen

```powershell
cd c:\NovusIntelligence\BancoSantaCruz\BancaConversacional
docker build -f PlanContainerizacion/FASE_1/Dockerfile -t genesis-api:local .
```

### 2. Configurar entorno

```powershell
Copy-Item PlanContainerizacion/FASE_1/.env.example .env
# Editar .env con AZURE_OPENAI_API_KEY, SEARCH, etc.
```

### 3. Levantar stack

```powershell
docker compose -f PlanContainerizacion/FASE_1/docker-compose.yml up -d
curl http://127.0.0.1:8445/health
```

### 4. Validar

```powershell
$env:GENESIS_ENDPOINT = "http://127.0.0.1:8445"
.\.venv\Scripts\python.exe Test_local\run_mvp.py --smoke
```

### 5. Deploy en VM (paralelo a 8446)

```bash
scp PlanContainerizacion/FASE_1/docker-compose.yml genesis@192.168.150.5:/opt/genesis-docker/
scp .env genesis@192.168.150.5:/opt/genesis-docker/.env
ssh genesis@192.168.150.5 'cd /opt/genesis-docker && docker compose pull && docker compose up -d'
```

## Criterios de aceptación

- [ ] Imagen < 500 MB
- [ ] `/health` → 200 en < 1 s
- [ ] `/pruebas` accesible con `GENESIS_SERVE_UI=true`
- [ ] 2 instancias API comparten sesión vía Redis (test manual: turn 1 en réplica A, turn 2 en réplica B)
- [ ] Smoke 17/17 OK contra contenedor
- [ ] Sin secretos en imagen ni en git
- [ ] Fallback in-memory si `GENESIS_REDIS_URL` vacío (solo dev local sin compose)

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| Redis no disponible | Health check falla; compose restart policy |
| Serialización snapshot Pydantic | JSON con `model_dump` / `model_validate` |
| Puerto 8445 ocupado en VM | Usar 8447 en compose hasta cutover |
| Latencia Redis | Redis en misma VM/red; pool de conexiones |

## Siguiente fase

Tras validar Fase 1 en lab → [FASE_2](../FASE_2/README.md) (Azure Container Apps).
