# Contenerización — Banca Conversacional

Alineado con `PlanContainerizacion/FASE_1/Dockerfile` y la imagen en la raíz del repo.

## Instancia de evolución (QA)

La evolución de la banca conversacional se hace en **Cognitiva QA :8447**
(`http://20.127.25.24:8447`), no en el puerto local 8445.

| Entorno | Puerto | Rol |
|---------|--------|-----|
| Local | 8445 | Dev / unit tests |
| QA VM | **8447** | Evolución + validación de producto |
| Legacy | 8446 | No modificar en deploys 8447 |
| Contenedores | 8448 | Paralelo Docker (opcional) |

Deploy Fase 1 a 8447:

```powershell
# 1) Build
.\.venv\Scripts\python.exe .\deploy\corp-8446\build_corp_package.py

# 2) Deploy (requiere SSH_DEPLOY_PASS)
$env:SSH_DEPLOY_PASS="..."
$env:SSH_HOST="20.127.25.24"
.\.venv\Scripts\python.exe .\deploy\corp-8447\deploy_ssh_password.py

# 3) Validar
$env:GENESIS_VALIDATE_BASE="http://20.127.25.24:8447"
.\.venv\Scripts\python.exe .\Test_local\validate_fase1_cases.py
```

UI de pruebas: http://20.127.25.24:8447/pruebas


## Build sugerido

```dockerfile
# Ya existente — asegurar COPY de data (FAQ + overlay) y opcionalmente docs
COPY data ./data
COPY prompts ./prompts
COPY docs ./docs
```

Comando runtime (existente):

```text
python scripts/run_contract_inspector.py
```

Healthcheck: `GET /health` en `GENESIS_PORT` (default 8445).

## Variables de entorno críticas

### Runtime cognitive

| Variable | Descripción |
|----------|-------------|
| `GENESIS_HOST` / `GENESIS_PORT` | Bind HTTP |
| `GENESIS_FAQ_PATH` | Ruta absoluta FAQ JSON dentro del contenedor |
| `GENESIS_FAQ_OVERLAY_PATH` | Overlay Fase 1 (expresiones) |
| `GENESIS_FAQ_INSTITUTIONAL_MIN_SCORE` | Default `0.65` |
| `GENESIS_PROFANITY_EXTRA` | CSV términos adicionales |
| `GENESIS_RAG_NO_HUMAN_ESCALATION_INSTITUTIONAL` | `1` recomendado |
| `AZURE_OPENAI_*` | Endpoint, key, deployments chat/embeddings |
| `AZURE_SEARCH_*` | Endpoint, key, index |
| Redis / Core URLs | Según `PlanContainerizacion/VARIABLES_ENTORNO.md` |

### Solo CI / job de documentación

| Variable | Descripción |
|----------|-------------|
| `GENESIS_API_EXCEL_PATH` | Excel API Productos |
| `GENESIS_KB_EXCEL_PATH` | Excel Base de Conocimiento |
| `GENESIS_DOCS_OUT_DIR` | Default `/app/docs` o artifact de CI |

```bash
python scripts/export_docs_from_excel.py
python scripts/import_kb_excel_vf01.py --excel "$GENESIS_KB_EXCEL_PATH" --from-row 79
```

## Volúmenes recomendados

| Mount | Motivo |
|-------|--------|
| `/app/data` (opcional RW) | Actualizar FAQ/overlay sin rebuild |
| `/app/docs` (opcional RO) | Documentación servida o auditada |
| Redis externo | Sesiones multi-réplica |

## Checklist migración a contenedores

1. [ ] `data/kb_faq_vf01.json` + `kb_faq_overlay_fase1.json` en la imagen o volumen  
2. [ ] Env Azure OpenAI + Search configurados en el orchestrator  
3. [ ] `GENESIS_FAQ_PATH` apunta a ruta del contenedor (`/app/data/...`)  
4. [ ] Redis reachable entre réplicas si hay más de un pod  
5. [ ] Healthcheck `/health` en probes de K8s/Compose  
6. [ ] Job CI regenera `docs/context-api` y `docs/business-rules` al cambiar Excel  
7. [ ] Tests `test_fase1_orchestration.py` en pipeline antes de promote  

## Compose (esqueleto)

```yaml
services:
  genesis-cognitive:
    image: genesis-api:local
    ports: ["8445:8445"]
    environment:
      GENESIS_HOST: "0.0.0.0"
      GENESIS_PORT: "8445"
      GENESIS_FAQ_PATH: "/app/data/kb_faq_vf01.json"
      GENESIS_FAQ_OVERLAY_PATH: "/app/data/kb_faq_overlay_fase1.json"
      GENESIS_RAG_NO_HUMAN_ESCALATION_INSTITUTIONAL: "1"
      AZURE_OPENAI_ENDPOINT: "${AZURE_OPENAI_ENDPOINT}"
      AZURE_OPENAI_API_KEY: "${AZURE_OPENAI_API_KEY}"
      AZURE_SEARCH_ENDPOINT: "${AZURE_SEARCH_ENDPOINT}"
      AZURE_SEARCH_API_KEY: "${AZURE_SEARCH_API_KEY}"
    volumes:
      - ./data:/app/data:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8445/health', timeout=3)"]
      interval: 30s
      timeout: 5s
      retries: 3
```
