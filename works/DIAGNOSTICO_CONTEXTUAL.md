# Diagnóstico contextual — interpretación banca conversacional

Fecha: 2026-09-19.

## Flujo efectivo `/turn`

1. `context_info=true` → carga snapshot (Core WS o `lab_fallback`) → Redis sesión CAS.
2. Turno NL con `GENESIS_SEMANTIC_MODE=azure_plan`:
   - Puente `deterministic_fastpath_pre_azure` (fecha pago / reclamación / fallecidos; **no** multi-intención).
   - Shortcut de selección pendiente.
   - `build_turn_envelope` → proyección tipada (sin saldos) → Azure Structured Outputs.
   - `interpretation_to_turn_plan` → `execute_turn_plan` → `merge_pending_tasks` → commit Redis.

## Contexto al modelo

`ProjectedProduct` ahora incluye: `masked_label`, `last_four`, `applicable_fields`, `classification`, `mapping_provenance`.  
`ProjectedConversationMemory`: `context_source`, `snapshot_revision`, `portfolio_completeness`, `projection_version=contextual-v1`.  
No se envían importes para resolver identidad.

## Hotfixes conservados

| Hotfix | Estado |
|---|---|
| Fecha límite de pago / reclamación / fallecidos (puente pre-Azure) | Conservado; excluido de compuestos P01 |
| Portfolio-aware tasa + alias tarjeta joven | Conservado |
| Redis/Entra QA | Conservado |
| `merge_pending_tasks` multi-campo | Conservado |

## Causas verificadas vs capturas históricas

| Caso | Histórico | Revisión |
|---|---|---|
| TC03 / GR03 / GR09 | Etiqueta Cumple | Contradicción visual (definición cliente / capital); no oráculo |
| Fecha pago / reclamación / fallecidos | Fallo post-azure_plan | Corregido por puente; re-verificado QA lab 2026-09-19 |
| Saldo tarjeta joven | — | Lab: resuelve alias; QA lab OK |

## Separación entornos

| Capa | Versión |
|---|---|
| Checkout local | Cambios proyección + catálogo campos + FAQ anti-«cliente» |
| QA `:8447` | Mismos módulos desplegados 2026-09-19 |
| Core vivo 726588 | Puede no traer Tarjeta Joven → AX-TJ `NOT_APPLICABLE` en Core |
