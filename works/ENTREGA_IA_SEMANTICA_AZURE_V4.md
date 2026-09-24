# Entrega — IA semántica Azure V4

Fecha: 2026-09-18.

## Objetivo verificable

Una formulación abierta se interpreta con el resolver Azure multiacción existente (`resolve_full`), se convierte en `TurnPlan`, se ejecuta con evidencia y se conserva el estado (pendientes/foco) vía `POST /turn`. No basta un JSON de interpretación.

## Comportamiento implementado

| Pieza | Detalle |
|---|---|
| Selector | `GENESIS_SEMANTIC_MODE=legacy\|azure_plan` (default `legacy`) |
| Ruta `azure_plan` | Scrub → atajo solo si cubre toda la solicitud → `resolve_full` → adaptador → `validate_turn_plan` → `execute_turn_plan` → CAS |
| Atajos | Opción estructurada (`N` / `opcion N`), refuse de secretos/terceros. **No** por palabra suelta («misión», «disponible», «segunda») en compuestos |
| Memoria al modelo | `conversation_memory`: pending_tasks, compare_set, foco, topic, claves de `catalog_personal_map` (sin saldos) |
| Fallo Azure | `PROVIDER_ERROR` + `not_heuristic_fallback=true`; **no** se etiqueta heurística como `source=azure` |
| Telemetría `/turn` | `audit.inference_count`, `audit.semantic_mode`, `audit.decision_trace`, deployment efectivo |
| Redis/Entra | Intacta (`redis_client_factory`, fail-closed QA) |

### Correcciones V3.1 residuales en este cambio

- Redacción de secretos **alfanuméricos** en historial (`redact_secret_digits_for_logs`).
- Merge de `pending_tasks` por `task_id` (no borrar familia no resuelta).
- Deployment telemetría vía `GENESIS_AZURE_DEPLOYMENT` / env (no hardcode ciego en proposer/verifier).

## Archivos principales

- `src/genesis_cognitive/brain/semantic_mode.py` — selector
- `src/genesis_cognitive/brain/azure_plan_adapter.py` — Interpretation → TurnPlan
- `src/genesis_cognitive/brain/azure_plan_turn.py` — orquestación turno V4 + merge pendientes
- `src/genesis_cognitive/model_input/model_input_builder.py` — memoria tipada
- `src/genesis_cognitive/demo/contract_inspector_app.py` — cableado `/inspect`+`/turn`
- `src/genesis_cognitive/agents/agent_framework_turn_resolver.py` — deployment dinámico
- `src/genesis_cognitive/brain/security_secrets.py` — redact alfanumérico
- `tests/unit/test_semantic_azure_v4.py`

## Comandos y resultados reales

```text
.\.venv\Scripts\python.exe -m pytest tests/unit/test_semantic_azure_v4.py -q --tb=short
→ 9 passed

.\.venv\Scripts\python.exe -m pytest ^
  tests/unit/test_semantic_azure_v4.py ^
  tests/unit/test_redis_entra_factory.py ^
  tests/unit/test_correccion_auditada_v3_1.py ^
  tests/unit/test_casos_adicionales_v3.py ^
  tests/unit/test_cierre_cognitivo_v3_1.py ^
  tests/unit/test_cognitive_improvement_v3.py -q --tb=line
→ 78 passed
```

**Azure real:** no ejecutado. Los tests usan `resolve_full` mockeado; no acreditan comprensión remota.

**Redis remoto / Entra:** no revalidado aquí; integración previa conservada.

## Activar / revertir en QA

Servicio: `genesis-cognitive-8447`  
Env: `/opt/genesis-cognitive-8447/Genesis_v2/.env`

### Activar V4 (tras backup)

```bash
cp /opt/genesis-cognitive-8447/Genesis_v2/.env \
   /opt/genesis-cognitive-8447/Genesis_v2/.env.bak.v4.$(date +%s)

# Añadir / upsert (sin tocar Foundry/Redis Entra existentes):
GENESIS_SEMANTIC_MODE=azure_plan
# Opcional: deployment efectivo
# GENESIS_AZURE_DEPLOYMENT=<nombre-deployment-qa>

sudo systemctl restart genesis-cognitive-8447
curl -sS http://127.0.0.1:8447/health
curl -sS http://127.0.0.1:8447/ready/redis   # si Redis Entra ya cableado
```

Verificar un `/turn` sintético y comprobar `audit.semantic_mode=azure_plan` y `audit.inference_count>=1` cuando el modelo responde.

### Revertir

```bash
# Quitar GENESIS_SEMANTIC_MODE o poner:
GENESIS_SEMANTIC_MODE=legacy
sudo systemctl restart genesis-cognitive-8447
```

O restaurar `.env.bak.v4.*`.

## Pendientes QA (concretos)

1. Azure real con fixtures sintéticos: paráfrasis / typos / corrección / mixtas (mismas fuentes que baseline).
2. Recorridos verticales de la §8 del prompt con deployment QA (disponible→USD; saldo contable; visión→retomar cuenta; tasa+definición; corrección+misión; dos pendientes).
3. Cliente 726588 lectura autorizada: origen real vs `lab_fallback`; sin atribuir productos ajenos.
4. Redis desde VM: continuidad de `pending_tasks` / `compare_set` entre procesos con Entra.
5. Medición p50/p95 tokens/latencia proposer+verifier; decidir si optimizar verifier.
6. Informe de brechas de corpus Foundry (sin actualizar índices en esta entrega).
7. Política de clúster Redis Non-Clustered + expulsión (operación Azure, no código).

## Límites

- No se modificó `BSC.genesis.conversational.backend`, frontend, WebSocket ni contratos externos de canal.
- No deploy PROD ni cambios Foundry.
- No se declara Azure real ni Redis remoto validados por mocks.
- DTO Azure (`ModelSemanticProposal`) no se amplió con todos los campos TurnPlan; el adaptador deriva campos/dominio en servidor. Extensión de schema structured-output queda como mejora si el deployment lo soporta.
