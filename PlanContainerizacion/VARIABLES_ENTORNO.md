# Variables de entorno

## API Genesis (`genesis-cognitive`)

| Variable | Requerida | Descripción | Ejemplo |
|----------|-----------|-------------|---------|
| `GENESIS_HOST` | No | Bind address | `0.0.0.0` |
| `GENESIS_PORT` | No | Puerto (8440–8449, ≠8443) | `8446` |
| `GENESIS_ENV` | No | dev / qa / prod | `prod` |
| `GENESIS_SERVE_UI` | No | Lab UI en `/` | `false` |
| `GENESIS_SQLITE_PATH` | No | DB demo local | `/data/modelo.sqlite` |
| `GENESIS_REDIS_URL` | Fase 1+ | Redis para sesiones | `redis://redis:6379/0` |
| `GENESIS_SESSION_TTL_S` | No | TTL sesión | `1800` |
| `GENESIS_SNAPSHOT_TTL_S` | No | TTL snapshot | `600` |
| `GENESIS_UVICORN_WORKERS` | No | Workers (default 1) | `2` |

## Azure OpenAI

| Variable | Requerida | Descripción |
|----------|-----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Sí | URL del recurso |
| `AZURE_OPENAI_API_KEY` | Sí* | API key (* o Managed Identity) |
| `AZURE_OPENAI_API_VERSION` | Sí | ej. `2024-10-21` |
| `AZURE_OPENAI_DEPLOYMENT` | Sí | Nombre deployment chat |

## Azure AI Search (RAG)

| Variable | Requerida | Descripción |
|----------|-----------|-------------|
| `AZURE_SEARCH_ENDPOINT` | Sí | URL search service |
| `AZURE_SEARCH_API_KEY` | Sí | API key |
| `AZURE_SEARCH_INDEX` | Sí | `genesis-kb` |

## Container Apps / Key Vault (Fase 2+)

Usar referencias secretas de ACA apuntando a Key Vault:

```bash
az containerapp secret set -n genesis-api -g rg-genesis-cognitive-mvp-eus \
  --secrets azure-openai-key=keyvaultref:https://kv-genesis.vault.azure.net/secrets/openai-key
```

## .env.example (local / Fase 1)

Ver `PlanContainerizacion/FASE_1/.env.example`.
