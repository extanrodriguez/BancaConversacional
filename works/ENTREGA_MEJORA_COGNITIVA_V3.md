# Entrega — Mejora cognitiva V3 (pruebas QA)

Fecha: 2026-09-18. Alcance: **capa cognitiva local**.  
Backend externo `BSC.genesis.conversational.backend`: **no modificado**.  
Sin despliegue, sin índices Foundry, sin transacciones, sin secretos ZIP.

## Baseline

| Campo | Valor |
|---|---|
| Checkout | Workspace `BancaConversacional` (sin git usable en esta máquina) |
| Entrada productiva | `POST /turn` (`contract_inspector_app`) |
| Versión app | `0.8.0` |
| FAQ | `data/kb_faq_vf01.json` (+ overlay si env) — `vf01-r80` misión, `vf01-r82` visión (score 1.0) |
| Redis / Azure real | **Separados**: no bloquean esta entrega; QA Redis sigue pendiente de Access Key |

## Qué se implementó

### 1. Institucional (misión / visión)
- `_is_institutional_entity_request` + ampliación de `_is_explicit_knowledge_request`.
- Heurística `critical:institutional_entity` (no clarificación genérica).
- Fastpath FAQ temprano incluye `mision`/`vision`/`valores` tras pending personal.
- Prueba: `test_mision_after_loan_focus_hits_faq`.

### 2. PIN / OTP / CVV antes de sufijos
- Nuevo [`security_secrets.py`](../src/genesis_cognitive/brain/security_secrets.py).
- Bloqueo en `run_field_fastpath`, `apply_digit_followup_guardrail`, `apply_card_digits_guardrail` y heurística.
- Colisión PIN=sufijo de producto → mensaje de seguridad, no ficha.

### 3. Titularidad de terceros
- Heurística ampliada (esposo/esposa/hijo/pareja + saldo/cuenta) → `security`.
- No devuelve saldo propio.

### 4. Disponible vs saldo actual (fallo QA A2/A3)
- Heurística: liquidez → `product=account`, `available` vs `balance`.
- `_generic_balance`: no mezcla préstamos en aclaraciones de disponible/actual.
- `apply_generic_balance_guardrail`: `ledger_balance` para “saldo actual”; `available_balance` para disponible; `null` ≠ cero.

### 5. TurnPlan (base V3)
- Nuevo [`turn_plan.py`](../src/genesis_cognitive/brain/turn_plan.py): `PlanTask`, `TurnPlan`, adaptador desde `IntentPacket`, validación mínima.
- Migración completa multi-tarea / comparación ordenada: **pendiente** (siguiente iteración).

### 6. Telemetría `/turn`
- `audit` enriquecido: `correlation_id`, `route_steps`, `brain_source`, `context_source`.
- Sin campos nuevos incompatibles en el contrato consumidor (sigue HTTP 200 + `app_channel`).

## Rutas modificadas / nuevas

| Ruta | Cambio |
|---|---|
| `src/genesis_cognitive/brain/security_secrets.py` | **nuevo** |
| `src/genesis_cognitive/brain/turn_plan.py` | **nuevo** |
| `src/genesis_cognitive/brain/azure_intent_brain.py` | institucional, secretos, liquidez→cuenta |
| `src/genesis_cognitive/brain/grounded_executor.py` | `_generic_balance` solo liquidez |
| `src/genesis_cognitive/router/field_guardrails.py` | auth secret, FAQ temprano, saldo actual |
| `src/genesis_cognitive/demo/contract_inspector_app.py` | audit correlación/ruta |
| `tests/unit/test_cognitive_improvement_v3.py` | **nuevo** |

## Comandos y resultados

```text
pytest tests/unit/test_cognitive_improvement_v3.py -v
# 9 passed

pytest tests/unit/test_cognitive_stabilization_stage1.py \
       tests/unit/test_cognitive_stabilization_stage1b.py -q
# 33 passed, 1 skipped

pytest tests/unit/test_cognitive_stabilization_stage1c.py \
       tests/unit/test_cognitive_stabilization_stage1c_close.py -q
# 27 passed, 2 skipped
```

## Antes / después (sanitizado)

| Caso | Antes (QA/diagnóstico) | Después (local) |
|---|---|---|
| `mision` tras préstamo | Clarificación genérica dominio | FAQ `vf01-r80` / knowledge |
| `¿Cuánto tengo disponible?` con cuenta+préstamos | Aclaración de **préstamos** | Cuenta / disponible |
| `¿saldo actual?` | Respondía disponible | `ledger_balance` + etiqueta “saldo actual” |
| `mi pin es 7615` | Riesgo de match a préstamo …7615 | Guardrail seguridad |
| `saldo de mi esposo` | Riesgo saldo propio | SECURITY_GUARDRAIL |

## Matriz de campos (extracto)

| Campo semántico | Contrato snapshot | Ausencia |
|---|---|---|
| `available` | `ProductSnapshot.available_balance` | Mensaje “dato ausente, no cero” |
| `balance` (saldo actual) | `ledger_balance` | Idem; no sustituir por available silenciosamente |
| PIN/OTP | N/A (nunca hecho) | Rechazo seguridad |

## Brechas KB / pendientes V3

| Ítem | Estado |
|---|---|
| TurnPlan multi-tarea (P01–P15, exclusiones, comparación ordenada) | Base lista; ejecución multi-tarea **pendiente** |
| CD13/GR02 pago mínimo / cancelación general vs personal | Parcial (security/FAQ eligibility); falta batería dedicada |
| MIX07 Multicrédito → “¿tengo yo ese producto?” | Pendiente |
| CC02/CC03 comparación catálogo | Pendiente (estado `compare_set`) |
| Redis QA Azure / concurrencia multiproceso | **Separado** — ver `works/REDIS_QA_WIRE_STATUS.md` |
| Azure structured outputs acreditado en QA | No declarado; audit local mejorado |
| Paquete `Modelo_Mejora_Cognitiva_QA_V3.md` / Word 236 casos | No hallado en Downloads; se trabajó desde el prompt V3 |

## Límites explícitos

- No se validó Redis multiproceso ni se cableó Access Key Azure Redis.
- No se re-ejecutó la matriz QA 726588 remota en esta entrega.
- No se modificó corpus FAQ productivo ni Foundry.
- Compatibilidad `/turn`: `SESSION_BUSY` / `CONTEXT_LOAD_BUSY` 503 **conservada** (sin cambios de contrato).

## Follow-up post-exploración (mismo día)

Hallazgos de [Explorar FAQ misión/visión](52978dda-4bc8-4998-b240-6c2dd9301635) y [Explorar PIN y saldos](f7222d8b-cc77-4746-b03e-2845c172f8a8) aplicados:

1. **FAQ institucional antes del Azure Brain** en `/turn` (`institutional_faq_pre_brain`).
2. **`is_personal_portfolio_faq_blocked`**: exime `_is_institutional_short` aunque haya pending `account_ref`.
3. **`resolve_option_pool`**: `PORTFOLIO_QUERY` de liquidez no cae a préstamos (causa UX A2).

Pruebas: `11 passed` en `test_cognitive_improvement_v3.py`.

