# Bugs conversacionales — Análisis y corrección

Documentación de los issues reportados en la UI de pruebas (capturas adjuntas) y su estado en código.

## Resumen

| # | Consulta usuario | Comportamiento incorrecto | Comportamiento esperado | Estado |
|---|------------------|-------------------------|-------------------------|--------|
| 1 | "Ahora dime la corriente" | Lista 2 cuentas de **ahorros** | "No tienes cuentas corrientes activas" | Corregido |
| 2 | "Dime el saldo de mi cuenta corriente" | "saldo para **None**" | Mensaje claro: sin corrientes o producto no encontrado | Corregido |
| 3 | "Saldo ahorros 4587 y corriente 7731" | "saldo para **None**" | Resolver 4587; indicar que 7731 no existe | Corregido |
| 4 | "Saldo de la cuenta 1234" | "saldo para **None**" | "La cuenta ...1234 no existe en tu portafolio" | Corregido |

## Causa raíz

### Bug 1 — Corriente vs ahorros

El guardrail genérico de saldo multi-cuenta (`apply_generic_balance_guardrail`) se ejecutaba **antes** de filtrar por tipo `CHECKING`. Al decir "corriente" sin productos corrientes, caía en listado de todas las cuentas activas (solo SAVINGS en portafolio Andres).

**Fix:** `apply_specific_deposit_balance_guardrail()` en `field_guardrails.py`:

```python
if type_filter == "CHECKING" and not typed:
    return "VALID_CONTRACT", ..., "no tienes cuentas corrientes activas..."
```

También reforzado en `deposit_guardrail.py` para clarificaciones.

### Bug 2–4 — "None" en respuesta

El template de saldo usaba `display_label_in_context(product)` cuando `product` o `account_ref` era `None` tras no resolver la entidad. Python renderizaba la cadena `"None"`.

**Fix:**
1. Fast-path `apply_specific_deposit_balance_guardrail` intercepta dígitos inexistentes → `_product_not_found_message()`.
2. `contract_inspector_app.py` valida `account_ref` contra snapshot antes del template final; si no existe → `_product_not_found_message()`.

Mensaje estándar:

> *"{nombre}, la cuenta ...1234 que quieres consultar no existe en tu portafolio activo."*

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `src/genesis_cognitive/router/field_guardrails.py` | Guardrail saldo específico, `_product_not_found_message` |
| `src/genesis_cognitive/router/deposit_guardrail.py` | Tipo sin productos |
| `src/genesis_cognitive/demo/contract_inspector_app.py` | Validación ref antes de template |
| `tests/unit/test_field_guardrails.py` | Tests corriente inexistente, 1234 |
| `Test_local/data/escenarios_routing.json` | Escenarios QA |

## Validación

### Tests unitarios

```powershell
pytest tests/unit/test_field_guardrails.py -q
# 11 passed
```

Casos clave:
- `test_specific_balance_no_checking` — "Ahora dime la corriente"
- `test_specific_balance_unknown_digits` — cuenta 1234

### Validación manual UI

Reiniciar servidor local antes de probar:

```powershell
powershell -ExecutionPolicy Bypass -File .\Test_local\start_local.ps1
```

Abrir http://127.0.0.1:8445/pruebas con portafolio **Andres david** (solo cuentas SAVINGS + TC):

| Mensaje | Respuesta esperada |
|---------|-------------------|
| Ahora dime la corriente | No tienes cuentas corrientes activas... |
| Dime el saldo de mi cuenta corriente | No tienes cuentas corrientes... (no "None") |
| Dime el saldo de la cuenta 1234 | ...1234... no existe... |
| Saldo ahorros 4587 y corriente 7731 | Saldo 4587 si existe; 7731 no existe |

### Smoke automatizado

```powershell
python Test_local/run_mvp.py --smoke
```

## Notas

- "Corriente" como adjetivo coloquial debe mapear siempre a `CHECKING`, nunca a SAVINGS.
- Nunca mostrar `None`, `null` ni placeholders internos al cliente.
- Si el producto existe pero el saldo no está en snapshot, mantener: *"El saldo se obtiene del Core"* con **nombre de cuenta correcto**, no None.
