# DR — Disaster Recovery (Fase 3)

## RPO / RTO objetivo

| Componente | RPO | RTO |
|------------|-----|-----|
| API (stateless) | 0 (imagen inmutable en ACR) | 15 min (rollback revision) |
| Redis sesiones | 5 min (último snapshot) | 30 min |
| Config / secretos | 0 (Key Vault) | 10 min |

## Backup Redis

### Lab (Basic)

- Sesiones efímeras: aceptable pérdida ≤ 30 min conversación activa
- Export manual antes de mantenimiento:

```bash
az redis export -n redis-genesis-lab -g rg-genesis-cognitive-mvp-eus \
  --container "https://storage.blob.core.windows.net/backups/redis.rdb"
```

### Prod (Premium recomendado)

- Geo-replication a region secundaria
- Persistence AOF habilitada

## Failover API

1. Activar revisión ACA conocida estable (RUNBOOK Fase 2)
2. Si ACA region down: redeploy bicep en region DR (requiere Redis replicado + OpenAI multi-region)

## Failover DNS

Application Gateway frontend IP fija → actualizar DNS CNAME solo en cutover planificado.

## Imágenes ACR

Retener tags `latest`, `{sha}`, `release-{date}` mínimo 90 días.

```bash
az acr repository show-tags -n acrgenesis871a5b --repository genesis-api -o table
```

## Validación DR (trimestral)

- [ ] Rollback revision probado
- [ ] Restore Redis RDB en instancia test
- [ ] Smoke completo post-restore
- [ ] Rotación secretos KV sin downtime
