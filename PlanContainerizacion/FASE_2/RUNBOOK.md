# Runbook — Genesis API en Azure Container Apps

## URLs útiles

```bash
RG=rg-genesis-cognitive-mvp-eus
APP=genesis-api

FQDN=$(az containerapp show -n $APP -g $RG --query properties.configuration.ingress.fqdn -o tsv)
echo "https://${FQDN}/health"
```

## Deploy manual (nueva imagen)

```bash
SHA=$(git rev-parse --short HEAD)
ACR=acrgenesis871a5b.azurecr.io

az acr login --name acrgenesis871a5b
docker build -t $ACR/genesis-api:$SHA .
docker push $ACR/genesis-api:$SHA

az containerapp update -n genesis-api -g $RG --image $ACR/genesis-api:$SHA
```

## Ver revisiones

```bash
az containerapp revision list -n genesis-api -g $RG -o table
```

## Rollback (< 5 min)

```bash
# Activar revisión anterior estable
PREV=$(az containerapp revision list -n genesis-api -g $RG \
  --query "sort_by(@, &properties.createdTime)[-2].name" -o tsv)
az containerapp revision activate -n genesis-api -g $RG --revision $PREV
```

## Escalar manualmente

```bash
az containerapp update -n genesis-api -g $RG --min-replicas 3 --max-replicas 15
```

## Rotar secretos OpenAI

```bash
az keyvault secret set --vault-name kv-genesis-cognitive \
  --name openai-api-key --value "$NEW_KEY"
# Reiniciar réplicas para refrescar secretRef
az containerapp revision restart -n genesis-api -g $RG
```

## Logs (Kusto)

```kusto
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "genesis-api"
| where Log_s contains "ERROR" or Log_s contains "500"
| order by TimeGenerated desc
| take 50
```

## Smoke post-deploy

```bash
export GENESIS_ENDPOINT="https://${FQDN}"
python Test_local/run_mvp.py --smoke
```

## Incidentes comunes

| Síntoma | Causa | Acción |
|---------|-------|--------|
| 502 en ingress | Container crash / OOM | Revisar logs; subir memory a 1.5Gi |
| Sesión perdida | Redis down / URL mal | Verificar GENESIS_REDIS_URL secret |
| 429 OpenAI | TPM excedido | Reducir maxReplicas; ampliar fast-path |
| Health fail | API key inválida | Rotar secret KV |
