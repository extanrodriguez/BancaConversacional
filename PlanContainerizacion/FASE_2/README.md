# Fase 2 — Azure Container Apps + ACR + Redis gestionado

**Duración estimada:** 3–4 semanas  
**Objetivo:** Migrar de Docker en VM a **Azure Container Apps** con imagen en ACR, sesiones en **Azure Cache for Redis**, secretos en **Key Vault** y pipeline CI/CD automatizado.

## Prerrequisitos

- [ ] Fase 1 completada y validada en lab
- [ ] `RedisSessionStore` en producción con tests verdes
- [ ] Smoke local contra contenedor OK
- [ ] Permisos Contributor en RG `rg-genesis-cognitive-mvp-eus`

## Recursos Azure a crear

| Recurso | Nombre sugerido | SKU / config |
|---------|-----------------|--------------|
| Container Registry | `acrgenesis871a5b` | Basic |
| Cache for Redis | `redis-genesis-lab` | Basic C1 |
| Key Vault | `kv-genesis-cognitive` | Standard |
| Log Analytics | `log-genesis-aca` | Pay-as-you-go |
| Container Apps Environment | `cae-genesis-eus` | Consumption |
| Container App | `genesis-api` | min 2, max 10 replicas |

## Arquitectura Fase 2

```text
GitHub / Azure DevOps
    │ push image
    ▼
ACR (acrgenesis871a5b.azurecr.io/genesis-api:{sha})
    │
    ▼
Container App (genesis-api) ──► Azure Cache Redis
    │                           Key Vault (MI)
    ├── Azure OpenAI (existente)
    └── Azure AI Search (existente)
```

## Pasos de alto nivel

1. Provisionar infra con Bicep (`containerapp.bicep`)
2. Subir secretos a Key Vault
3. Configurar Managed Identity en Container App
4. Pipeline: build → push ACR → `az containerapp update`
5. Smoke remoto post-deploy
6. Cutover DNS/puerto desde VM docker → ACA (coordinado con infra)

## Criterios de aceptación

- [ ] minReplicas=2, tráfico repartido sin pérdida de sesión
- [ ] Secretos solo en Key Vault / ACA secrets
- [ ] Deploy automatizado en < 10 min
- [ ] Rollback a revisión anterior en < 5 min
- [ ] `/health` y smoke remoto OK
- [ ] Latencia fast-path p95 < 100 ms desde ACA

## Coste estimado (lab)

| Servicio | ~USD/mes |
|----------|----------|
| ACA (2 réplicas mín) | 30–80 |
| Redis Basic C1 | 15–20 |
| ACR Basic | 5 |
| Log Analytics | 5–15 |

## Siguiente fase

[FASE_3](../FASE_3/README.md) — App Gateway, WAF, observabilidad producción.
