# Entrega Etapa 1C — interferencia FAQ + CAS/QA

Fecha: 2026-09-17. Sin llamadas remotas. Sin migración de índice. Sin tocar frontend / WebSocket / orquestador externo / `contract_inspector_app` / contratos externos.

## Diff (archivos)

| Archivo | Cambio |
|---|---|
| `src/genesis_cognitive/router/faq_guardrail.py` | Elegibilidad personal/definición/mixta; quita `tasa` suelta de knowledge_signals |
| `src/genesis_cognitive/router/field_guardrails.py` | DAP no monopoliza tasa genérica ni listados `mis certificados` |
| `src/genesis_cognitive/router/snapshot_guardrails.py` | `cuál es mi tasa?` → préstamo personal |
| `src/genesis_cognitive/brain/continuity.py` | `currency_unique` no come preguntas completas de saldo |
| `tests/unit/test_cognitive_stabilization_stage1c.py` | Suite 1C (FAQ real, DOP/USD, CAS, QA skip) |
| `tests/unit/test_fase1_orchestration.py` | Acepta step `bank_catalog` además de `faq` |
| `works/CAS_REVISION_1C.md` | Callers, conflicto, refs mutables, bloqueo HTTP |
| `works/QA_AZURE_REAL_1C.md` | Harness QA Azure (no ejecutado) |

## Pruebas ejecutadas

```text
.\.venv\Scripts\python.exe -m pytest `
  tests/unit/test_cognitive_stabilization_stage1c.py `
  tests/unit/test_cognitive_stabilization_stage1b.py `
  tests/unit/test_cognitive_stabilization_stage1.py `
  tests/unit/test_field_guardrails.py `
  tests/unit/test_conversation_context_kb.py `
  tests/unit/test_fase1_orchestration.py `
  tests/unit/test_azure_brain_grounded.py -v
```

**Resultado: 104 passed, 2 skipped** (ambos skip = QA Azure real, sin autorización).

## Fallos corregidos

1. FAQ corpus real robaba `¿Cuánto tengo disponible?` (topic ortografía coloquial) → bloqueado por elegibilidad.
2. `¿Cuál es mi tasa?` caía en DAP (“no tienes depósitos”) → préstamo / no FAQ.
3. Continuity `currency_unique` absorbía `balance … en pesos/dólares` sin pending → `specific_balance`.
4. Definiciones irrelevantes (p.ej. Cargo ante saldo disponible) → abstención o hit relevante.

## Riesgos pendientes

- Ref mutable: `get_session` devuelve la misma instancia del dict interno.
- `/inspect` sin `expected_revision` → concurrencia HTTP **no** protegida.
- Corpus sin entrada útil para “qué significa saldo disponible” → depende de Foundry en QA.
- Pregunta mixta: FAQ no consume; aún no hay respuesta dual fusionada en un solo turno.

## Validaciones que requieren autorización remota

- QA Azure real (`works/QA_AZURE_REAL_1C.md`) — **no ejecutada, no hay éxito Azure que declarar**.
- Cableado CAS en callers de `contract_inspector_app` — documentado, no aplicado.
- Migración de índice de conocimiento — fuera de alcance 1C.
