# Resumen corrida `20260921T105853Z_4f3d3488`

- Inicio UTC: 20260921T105853Z
- Fin UTC: 20260921T130020Z
- Endpoint: `http://20.127.25.24:8447`
- Alcance: all
- lab_fallback: True
- Cliente: 726588 (lectura)

## Conteos

```json
{
  "inventoried": 236,
  "selected": 236,
  "executed": 236,
  "PASS_RESOLVED": 73,
  "PASS_CLARIFICATION_EXPECTED": 8,
  "PARTIAL_CAPABILITY": 56,
  "PENDING_EVALUATION": 1,
  "FAIL_INTERPRETATION": 30,
  "FAIL_RETRIEVAL": 7,
  "FAIL_STATE": 4,
  "FAIL_GROUNDING": 51,
  "BLOCKED_DEPENDENCY": 6,
  "NOT_EXECUTED": 0,
  "turns": 387
}
```

Resumen: exec=236/236 OK=73+clar=8 partial=56 pending_eval=1 fail=92 blocked=6

## Notas

- Las etiquetas históricas de la guía no son oráculo.
- Core vivo vs lab se registra por `context_source` en cada turno.
