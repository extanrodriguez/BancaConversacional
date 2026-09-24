# Entrega — Cierre cognitivo V3.1 (local)

Fecha: 2026-09-18. Alcance: **capa cognitiva local** cableada a `POST /turn`.  
Backend externo `BSC.genesis.conversational.backend`: **no modificado** (ruta ausente o sin checkout usable en este workspace; sin cambios aplicados).  
Sin despliegue, sin índices Foundry, sin transacciones, sin secretos ZIP.

## 1. Insumos leídos

| Archivo | Ruta | Validación |
|---|---|---|
| Prompt cierre | `works/Banca_Cierre_V3_1/Prompt_Cursor_Cierre_V3_1.md` | leído |
| Modelo V3 | `works/Banca_Cierre_V3_1/insumos/Modelo_Mejora_Cognitiva_QA_V3.md` | leído |
| Prompt pruebas QA | `works/Banca_Cierre_V3_1/insumos/Prompt_Cursor_Banca_V3_Pruebas_QA.md` | presente |
| 236 extraídos | `works/Banca_Cierre_V3_1/insumos/Casos_QA_236_Extraidos.jsonl` | **236** líneas / **236** `case_id` únicos |
| 24 propuestos | `works/Banca_Cierre_V3_1/insumos/Casos_QA_Adicionales_V3.jsonl` | **24** líneas / **24** `case_id` únicos |
| Resumen | `works/Banca_Cierre_V3_1/insumos/Resumen_QA.json` | presente |
| Entrega V3 previa | `works/ENTREGA_MEJORA_COGNITIVA_V3.md` | baseline conservada |

Versionado: **sin git usable**. Huella en `works/MANIFEST_SHA256_CIERRE_V3_1.json`.

## 2. Qué se implementó

### TurnPlan multi-tarea en `/turn`
- `brain/plan_interpreter.py`: interpreta el **mensaje completo + estado** → varias tareas (personal / institutional / catalog / process / refuse).
- `brain/plan_executor.py`: ejecuta tareas independientes, compone evidencia, propone mutaciones de estado.
- Cableado en `contract_inspector_app._inspect_unlocked` **antes** del FAQ institucional y del Azure Brain.
- Fastpath FAQ institucional solo si `message_is_institutional_only` (no omite subtareas personales).
- Telemetría: `decision_trace.step=turn_plan_multi` con `task_count`, `task_statuses`, `transition`, `secret_scrubbed`.

### Estado de sesión (schema_version 2)
- `pending_tasks`, `compare_set`, `process_focus` en `SessionState`.
- Serialización compatible en `redis_session_store` (defaults si faltan).
- Prioridad: instrucción actual → pendiente compatible → foco; excursión institucional no borra pendiente personal.

### Catálogo / existencia / comparación
- MIX07: `check_existence` con mapeo autorizado (no saldo de cuenta).
- CC02/CC03: `compare_set` ordenado; agregar producto actualiza el conjunto.
- CD13: definición de pago mínimo sin selección de tarjeta personal.
- GR02: comparación de procesos de cancelación sin payoff personal (código listo; E2E no dedicado).

### Hotfixes V3 conservados
- Liquidez → cuenta salvo foco/mención de tarjeta.
- PIN/OTP antes de sufijos; historial con dígitos depurados.
- Titularidad ajena vs pregunta general («abrir cuenta para mi hijo»).
- 11 pruebas V3 previas: **siguen pasando**.

## 3. Ruta efectiva `/turn`

```
POST /turn → inspect
  → scrub secretos (entrada)
  → interpret_turn_plan(mensaje, sesión, snapshot)
  → si plan multi/heurístico: execute_turn_plan → CAS → app_channel
  → si solo institucional: FAQ pre-brain (pending personal conservado)
  → else: Azure brain / fastpaths históricos
```

## 4. Cinco recorridos (E2E `/turn`)

| # | Recorrido | Test | Resultado |
|---|---|---|---|
| 1 | Foco tarjeta → disponible; mención cuenta; definición saldo disponible | `test_journey1_*` | passed |
| 2 | Misión + disponible en un mensaje; misión sola; retomar préstamo | `test_journey2_*` + misión/visión | passed |
| 3 | Multi-campo tarjeta + aclaración; DAP tasa/vencimiento sin balance ni tarjetas | `test_journey3_*` | passed |
| 4 | Multicrédito → «¿tengo yo ese producto?»; compare + agregar | `test_journey4_*` + CD13 | passed |
| 5 | PIN depurado en historial; esposo bloqueado; hijo/apertura general | `test_journey5_*` | passed |

## 5. Comandos y resultados

```text
.venv\Scripts\python.exe -m pytest `
  tests/unit/test_cierre_cognitivo_v3_1.py `
  tests/unit/test_cognitive_improvement_v3.py -v
# 21 passed
```

## 6. Matriz de cobertura

Archivo: `works/MATRIZ_COBERTURA_CIERRE_V3_1.json` (260 = 236 + 24).

| Estado | Cantidad | Nota |
|---|---:|---|
| passed | 9 | P01, P15, CD13, MIX07, CC02, CC03, X05, X07, IG01 (muestra ejercida) |
| not_executed | 251 | Importados; **no** cuentan como aprobados |
| failed / blocked | 0 | — |

No se deriva un % de mejora comparando 21 tests unitarios con los 236 del Word.

## 7. Pendientes separados (remotos / no bloqueantes)

| Ítem | Estado |
|---|---|
| Redis QA Access Key / concurrencia multiproceso | Separado (`REDIS_QA_WIRE_STATUS.md`) |
| Azure structured outputs en deployment real | No acreditado aquí; intérprete heurístico local |
| Matriz 236 completa + 24 adicionales E2E | Importada; ejecución masiva pendiente |
| GR02 / D04 adjudicación fina | Código/proceso parcial; E2E dedicado pendiente |
| Cliente QA 726588 remoto | No re-ejecutado; fixtures sintéticos para TC/DAP/USD |

## 8. Límites

- Frontend / WebSocket / contrato consumidor: sin cambios de contrato (`SESSION_BUSY` 200 string; `CONTEXT_LOAD_BUSY` 503).
- No se inicializó git padre ni se tocó el backend externo.
- V3.1 **cierra el alcance local** de multi-tarea + estado + catálogo/personal en `/turn`; no declara el sistema productivo «V3 completa» frente a Azure/Redis/matriz Word.
