# Estado QA :8447 — Lab8446 Foundry+Redis (2026-09-22)

## Qué hay en :8447
Runtime **BancaConversacional8446** (`lab8446`) expuesto en puerto **8447**.

- Servicio: `genesis-cognitive-8447.service`
- Path: `/opt/genesis-cognitive-8447/lab8446_runtime`
- Backup previo Genesis_v2: `/opt/genesis-cognitive-8447/backups/genesis_v2_pre_lab8446_*`
- Legacy :8446: **inactive** (no tocado)

## Redis WRITE PATH (intocable)
`POST /turn` con `context_info=true` → `ContextPersistenceService` (sibling) + sync portafolio lab.

- `LAB8446_KEY_PREFIX=` (vacío, keys orquestador)
- Cliente Redis Entra MI reutilizado (sin segundo `create_and_ping`)
- Meta UI en `labmeta:{conversation_id}` para no pisar `session:{id}` genesis

## Smoke verificado
| Check | Resultado |
|-------|-----------|
| GET /health | `lab8446-foundry-redis` port 8447 |
| GET /ready | redis ok, entra_managed_identity |
| context_info | `CONTEXT_LOADED`, `genesis_write: true` |
| compara Full Car vs Joven | tool `get_customer_products` OK, tasas/disponibles |

## AOAI
Chat: `gpt-4o-mini` (lab). Redis/session: Genesis_v2.

## Redeploy
`deploy/corp-8447/promote_lab8446_to_8447.py` (+ `SSH_DEPLOY_PASS`)
