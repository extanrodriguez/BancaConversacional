# Plan de Containerización — Banca Conversacional Genesis

Plan maestro para migrar la API cognitiva desde **VM + systemd + uvicorn único** hacia **contenedores autoescalables** en Azure, con CI/CD automatizado y sesiones compartidas en Redis.

## Documentos

| Archivo | Contenido |
|---------|-----------|
| [00_ARQUITECTURA_OBJETIVO.md](./00_ARQUITECTURA_OBJETIVO.md) | Diagrama, componentes, decisiones |
| [VARIABLES_ENTORNO.md](./VARIABLES_ENTORNO.md) | Catálogo de env vars por entorno |
| [CHECKLIST_GLOBAL.md](./CHECKLIST_GLOBAL.md) | Checklist transversal fases 1–3 |
| [FASE_1/README.md](./FASE_1/README.md) | Docker + Redis + VM (lab) |
| [FASE_1/PROMPT_IMPLEMENTACION.md](./FASE_1/PROMPT_IMPLEMENTACION.md) | **Prompt completo** para el agente |
| [FASE_1/docker-compose.yml](./FASE_1/docker-compose.yml) | Compose de referencia |
| [FASE_1/Dockerfile](./FASE_1/Dockerfile) | Dockerfile de referencia |
| [FASE_2/README.md](./FASE_2/README.md) | Azure Container Apps + ACR |
| [FASE_2/PROMPT_IMPLEMENTACION.md](./FASE_2/PROMPT_IMPLEMENTACION.md) | **Prompt completo** para el agente |
| [FASE_2/containerapp.bicep](./FASE_2/containerapp.bicep) | IaC de referencia |
| [FASE_3/README.md](./FASE_3/README.md) | Producción, HA, observabilidad |
| [FASE_3/PROMPT_IMPLEMENTACION.md](./FASE_3/PROMPT_IMPLEMENTACION.md) | **Prompt completo** para el agente |
| [FASE_3/DR.md](./FASE_3/DR.md) | Disaster recovery |
| [FASE_3/cutover_checklist.md](./FASE_3/cutover_checklist.md) | Cutover VM → prod |
| [FASE_2/RUNBOOK.md](./FASE_2/RUNBOOK.md) | Operaciones ACA |
| [FASE_1/REDIS_SESSION_STORE_SPEC.md](./FASE_1/REDIS_SESSION_STORE_SPEC.md) | Spec técnica Redis |
| [BUGS_CONVERSACIONALES.md](./BUGS_CONVERSACIONALES.md) | Bugs UI corriente/None |

## Resumen por fase

### Fase 1 — Docker en VM (2–3 semanas)
- Dockerizar API + Redis local
- Externalizar `ReactiveSessionStore` → Redis
- CI: build imagen + pytest + smoke
- Deploy en la misma VM con `docker compose`
- **Sin cambiar** puerto 8446 corporativo hasta validación

### Fase 2 — Azure Container Apps (3–4 semanas)
- Azure Container Registry (ACR)
- Container Apps con min 2 / max N réplicas
- Azure Cache for Redis
- Key Vault + Managed Identity
- Pipeline: push imagen → update revision → smoke remoto

### Fase 3 — Escala producción (continuo)
- Application Gateway + WAF + TLS
- Autoescala por concurrencia HTTP
- App Insights (latencia, inference_count, 429 OpenAI)
- Circuit breaker / rate limiting
- Entornos dev / qa / prod aislados

## Estado actual (baseline)

```
VM vm-test002-genesis (192.168.150.5)
  systemd genesis-cognitive-8446.service
  1 worker uvicorn
  ReactiveSessionStore in-memory
  Deploy manual: scp + deploy_8446.sh
  Azure OpenAI: aoai-genesis-871a5b (eastus)
```

## Cómo usar los prompts

1. Abrir el `PROMPT_IMPLEMENTACION.md` de la fase correspondiente.
2. Copiar el bloque **PROMPT PARA CURSOR** completo en un chat nuevo.
3. El agente debe implementar, probar y documentar antes de pasar a la siguiente fase.
4. Marcar ítems en `CHECKLIST_GLOBAL.md`.

## Criterios de éxito globales

- [ ] `Test_local/run_mvp.py --smoke` pasa en local y en QA remoto
- [ ] Consultas fast-path < 100 ms p95
- [ ] Consultas LLM < 8 s p95 (limitado por OpenAI)
- [ ] 2+ réplicas sin perder contexto de conversación
- [ ] Rollback de deploy en < 5 minutos
- [ ] Cero secretos en git
