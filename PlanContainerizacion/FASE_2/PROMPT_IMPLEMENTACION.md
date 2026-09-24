# Fase 2 — Prompt de implementación para Cursor

> Copia el bloque entre `--- INICIO PROMPT ---` y `--- FIN PROMPT ---` en un chat nuevo (Agent).

---

## --- INICIO PROMPT ---

Implementa la **Fase 2 de containerización**: desplegar Genesis Cognitive en **Azure Container Apps** con ACR, Redis gestionado, Key Vault y CI/CD.

### Prerrequisito

La **Fase 1 debe estar completa**:
- Dockerfile en raíz
- `RedisSessionStore` funcionando
- Smoke local contra docker compose OK

Si Fase 1 no está hecha, implementa primero siguiendo `PlanContainerizacion/FASE_1/PROMPT_IMPLEMENTACION.md`.

### Contexto Azure

| Parámetro | Valor |
|-----------|-------|
| Subscription | `871a5b90-0204-450e-b968-3190e9143faf` |
| Resource Group | `rg-genesis-cognitive-mvp-eus` |
| Region | `eastus` |
| OpenAI existente | `aoai-genesis-871a5b` |
| AI Search existente | `genesis-search-lab` |
| VM legacy | `192.168.150.5` puerto 8446 (NO apagar hasta cutover) |

### Objetivos

1. Provisionar ACR, Azure Cache Redis, Key Vault, Log Analytics, CAE, Container App.
2. Pipeline build → push ACR → update revision ACA.
3. Secretos vía Key Vault + Managed Identity (sin keys en git).
4. minReplicas=2, autoescala HTTP concurrentRequests=50.
5. Smoke remoto post-deploy.
6. Documentar rollback y runbook.

### Tareas

#### T1 — Infraestructura (Bicep)

Usar/adaptar `PlanContainerizacion/FASE_2/containerapp.bicep`:

```bash
az deployment group create \
  -g rg-genesis-cognitive-mvp-eus \
  -f PlanContainerizacion/FASE_2/containerapp.bicep \
  -p imageTag=latest minReplicas=2 maxReplicas=10
```

Ajustar nombres si hay colisión (ACR names globally unique).

Post-deploy:
- Asignar rol `AcrPull` a la MI del Container App sobre ACR
- Asignar rol `Key Vault Secrets User` sobre Key Vault
- Crear secretos en KV: `openai-api-key`, `search-api-key`

#### T2 — Secretos Key Vault

```bash
az keyvault secret set --vault-name kv-genesis-cognitive \
  --name openai-api-key --value "$AZURE_OPENAI_API_KEY"
az keyvault secret set --vault-name kv-genesis-cognitive \
  --name search-api-key --value "$AZURE_SEARCH_API_KEY"
```

Nunca commitear valores.

#### T3 — Push imagen inicial

```bash
az acr login --name acrgenesis871a5b
docker build -t acrgenesis871a5b.azurecr.io/genesis-api:$(git rev-parse --short HEAD) .
docker push acrgenesis871a5b.azurecr.io/genesis-api:$(git rev-parse --short HEAD)
az containerapp update -n genesis-api -g rg-genesis-cognitive-mvp-eus \
  --image acrgenesis871a5b.azurecr.io/genesis-api:$(git rev-parse --short HEAD)
```

#### T4 — CI/CD

Implementar pipeline basado en `PlanContainerizacion/FASE_2/azure-pipeline.yml`:
- Trigger en push a `main`
- Build + push con tag SHA
- Update container app
- Smoke: `GENESIS_ENDPOINT=https://{fqdn} python Test_local/run_mvp.py --smoke`

Para GitHub Actions, usar `azure/login@v2` con OIDC o service principal en secrets.

#### T5 — Validación multi-réplica

1. Obtener FQDN: `az containerapp show -n genesis-api -g ... --query properties.configuration.ingress.fqdn`
2. Enviar 20 requests concurrentes; verificar distribución en logs
3. Test sesión: conversation_id fijo, 2 turns; no debe perder contexto

#### T6 — Networking (lab)

- Ingress externo HTTPS en ACA (certificado gestionado por Azure)
- Si red corporativa requiere IP allowlist, documentar IPs de salida ACA
- Redis: solo acceso desde CAE (private endpoint opcional fase 2.1)

#### T7 — Observabilidad básica

- Logs en Log Analytics: query Kusto para errores 5xx
- Métrica custom opcional: log `inference_count` ya existe en respuesta JSON

#### T8 — Runbook

Crear `PlanContainerizacion/FASE_2/RUNBOOK.md` con:
- Deploy manual
- Rollback revision
- Escalar réplicas manualmente
- Rotar secretos KV

### Restricciones

- NO apagar VM 8446 hasta sign-off QA
- NO commitear secretos
- NO cambiar deployment OpenAI existente
- Puerto contenedor interno 8445 (ingress ACA mapea HTTPS→8445)

### Criterios de aceptación

1. `az containerapp show` → running, 2+ replicas ready
2. `curl https://{fqdn}/health` → 200
3. Smoke remoto 17/17
4. Sesión persiste entre requests a distintas réplicas
5. Pipeline verde en CI
6. Rollback probado (< 5 min)

### Entregables

- Bicep desplegado (o script az cli equivalente documentado)
- Pipeline en repo
- RUNBOOK.md
- Resumen URLs, comandos, pendientes Fase 3

## --- FIN PROMPT ---
