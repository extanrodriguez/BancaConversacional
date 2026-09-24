# Pivot Azure-cerebro + snapshot/KB como única boca de hechos

| Campo | Valor |
|-------|-------|
| Fecha | 2026-09-15 |
| Flag | `GENESIS_AZURE_BRAIN=1` |
| Estado | Fase 1 implementada (opt-in) |

## Principio

> Azure entiende la intención; el snapshot Core y la KB son la única boca de hechos; la matriz VF01 juzga si la respuesta es correcta.

## Qué cambió (Fase 1)

1. Paquete `src/genesis_cognitive/brain/`
   - `core_facts_catalog.py` — semántica oficial API Productos → snapshot
   - `azure_intent_brain.py` — IntentPacket (Azure JSON + heurística de seguridad)
   - `grounded_executor.py` — responde solo con campos reales del snapshot
   - `turn_orchestrator.py` — personal grounded / knowledge FAQ→Foundry
2. Hook en `POST /turn` **antes** del fastpath histórico (si el flag está ON).
3. Fallbacks de seguridad: cuánto≠cuándo, débito≠crédito, pago próximo≠DAP.

## Semántica Core crítica (no improvisar)

| Pregunta cliente | Campo API correcto | Snapshot | Prohibido |
|------------------|--------------------|----------|-----------|
| Disponible TC | `availablePurchasesDomestic` | `available_purchases_domestic` | usar `availableBalance` (eso es límite) |
| Adeudado TC | `currentBalance` | `ledger_balance` | |
| Límite TC | `availableBalance` | `credit_limit` | |
| Capital préstamo | `currentBalance` | `outstanding_principal` | |
| Mora | `pendingBalancePr` | `overdue_amount` | usarla como cuota |
| Próxima fecha pago | `nextPaymentDatePr` / `nextInstallmentDatePr` | `next_due_date` | `maturityDate` |
| Monto cuota | **no existe en API portafolio** | `installment_amount=0` | inventar / usar mora |
| DAP capital | `currentBalance` | `ledger_balance` | |

## Flujo con flag ON

```
/turn
  → Azure Intent Brain (JSON) [fallback heurístico]
  → Grounded executor
       personal → solo snapshot
       knowledge → FAQ → Foundry
  → si fallthrough → fastpath histórico (sin romper)
```

## Cómo probar

```bash
# local
set GENESIS_AZURE_BRAIN=1
pytest tests/unit/test_azure_brain_grounded.py -q
```

Casos QA:
- `Cuanto es mi proxima cuota?` → no disponible cuota (no fecha como monto)
- `Cuando es mi proxima cuota?` → `2026-08-25`
- `tarjetas de debito…` → mensaje débito (no options TC)
- `prestamo o tarjeta con pago proximo` → resumen (no DAP 5511)

## Próximas fases

2. ~~Redacción natural Azure **después** de armar facts (prosa, sin inventar números).~~ → `natural_draft.py` + `GENESIS_AZURE_DRAFT=1`
3. Memoria de sesión (resumen de hilo) alimentando el Intent Brain.
4. Ingesta de filas P0 de `Matriz_Cuentas` VF01 como few-shots / jueces.
5. Scorecard golden vs :8447.
