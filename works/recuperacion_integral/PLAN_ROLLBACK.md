# PLAN_ROLLBACK.md

Fecha: 2026-09-21 · Fase: contención P0

## Principio

Rollback **controlado y atribuible**. No sobrescribir Redis/sesión incompatible. No revertir mejoras independientes (índice candidato limpio, fix temperature gpt-6) sin justificación.

## Artefactos de restauración disponibles

| Artefacto | Ubicación | Uso |
|---|---|---|
| Snapshot local P0 | `works/recuperacion_integral/snapshots/20260921T204551Z/` | Código cognitivo local + fingerprints |
| ZIP deploy | `deploy/corp-8446/dist/genesis_corp_8446.zip` (SHA en ENTREGA_DESPLIEGUE_QA) | Paquete base del día |
| Backup remoto VM | `/opt/genesis-cognitive-8447/backups/` (p. ej. `genesis_v2_20260921_102720.tar.gz`) | Restaurar árbol app QA |
| Índice protegido | `bsc-kb-conocimiento` (980) | **No borrar**; rollback Search = cambiar env |
| Índice candidato | `bsc-kb-qa-vnext-20260921` (219) | Activo ahora; reversible vía `AZURE_SEARCH_INDEX` |

## Procedimientos (orden de preferencia)

### R1 — Solo configuración (bajo riesgo)

Cambiar en VM `.env` y reiniciar `genesis-cognitive-8447`:

- `AZURE_OPENAI_CHAT_DEPLOYMENT` / `GENESIS_AZURE_DEPLOYMENT`: `gpt-6-astra` → `gpt-4o-mini` (si se confirma regresión de schema/modelo)
- `AZURE_SEARCH_INDEX`: candidato → `bsc-kb-conocimiento` **solo** si se demuestra que el candidato rompe capacidades acreditadas (hoy: CMP no mejoró; otras capacidades pueden depender del limpio)

### R2 — Hotfix selectivo de archivos

Restaurar desde snapshot/backup **solo** archivos causantes probados. Hoy LOCAL≠QA en:

- `azure_plan_turn.py`
- `field_guardrails.py`
- `contract_inspector_app.py`

Antes de empujar local→QA o QA→local: diff y prueba de capacidades afectadas.

### R3 — Restaurar tarball remoto

```bash
# en VM (operador)
# 1) detener servicio
# 2) mover Genesis_v2 a Genesis_v2.bak_<ts>
# 3) extraer backup elegido
# 4) reaplicar .env actual (Search/modelo) conscientemente
# 5) start + health/ready
```

Comprobar compatibilidad de esquema Redis/session antes de tráfico.

### R4 — Prohibido en P0

- Borrar `bsc-kb-conocimiento`
- Promote learning / ejemplos
- Cambios FE / .NET / WS
- PROD

## Gate post-rollback

Smoke multi-capacidad + subset P0 acreditado. No declarar recuperación integral sin revalidar matriz.
