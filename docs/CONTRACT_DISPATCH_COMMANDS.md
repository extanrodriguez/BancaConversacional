# Contract Dispatch — Comandos Deterministas (Canonico Genesis 1.2)

Endpoint: `POST /contract-lab/dispatch?phase=VALIDATE`  
Body: `{"question": "<comando>", "customer_id": "<id>", "conversation_id": "<uuid>"}`

Fuente de verdad: `contratos/GENESIS_Contratos_Canonicos_Capa_Cognitiva_v1.md`  
Cognitiva NUNCA ejecuta Core. Solo emite `operation_request` 1.2.

## Pairs implementados

### Queries (nature=query, phase=QUERY)

| Pair | Operation | Capability | Comando |
|------|-----------|------------|---------|
| P01 | PASSIVE_PORTFOLIO_QUERY | PORTFOLIO | `Consulta portafolio` |
| P09 | ACTIVE_PORTFOLIO_QUERY | PORTFOLIO | `Consulta portafolio activo` |
| P02 | SAVINGS_ACCOUNT_QUERY | ACCOUNTS | `Consulta saldo cuenta {id} [moneda {ccy}]` |
| P03 | CHECKING_ACCOUNT_QUERY | ACCOUNTS | `Consulta cuenta corriente {id}` |
| P04 | CDT_QUERY | INVESTMENTS | `Consulta cdt {id}` |
| P10 | CREDIT_CARD_QUERY | CREDIT_CARD | `Consulta tarjeta {id}` |
| P12 | LOAN_QUERY | LOAN | `Consulta prestamo {id}` |
| P12 | LOAN_QUERY (cuota) | LOAN | `Consulta cuota prestamo {id}` |
| P13 | LOAN_SIMULATION_QUERY | LOAN | `Simula prestamo tipo {T} monto {n} plazo {m} moneda {ccy}` |
| P15 | LOAN_APPLICATION_AND_DOCUMENT_QUERY | LOAN | `Consulta requisitos prestamo` |
| P15 | LOAN_APPLICATION_AND_DOCUMENT_QUERY | LOAN | `Consulta estado solicitud {app_id}` |
| P05 | TRANSFER_POLICY_AND_TRACKING_QUERY | ACCOUNTS | `Rastrea transferencia {ref}` |

### Mutantes (nature=mutant, phase=VALIDATE por defecto)

| Pair | Operation | Category | Comando |
|------|-----------|----------|---------|
| M01 | TRANSFER_OWN_VALIDATE | TRANSFER_OWN | `Dispara movimiento cuenta origen {A} a cuenta destino {B} valor {N} moneda {CCY}` |
| M10 | LOAN_SERVICING_VALIDATE | LOAN_PAYMENT | `Paga prestamo {id} valor {N} moneda {CCY}` |
| P14 | LOAN_SERVICING_VALIDATE | LOAN_PAYMENT | `Abono capital prestamo {id} valor {N} moneda {CCY} [regla REDUCIR_PLAZO\|REDUCIR_CUOTA]` |
| P11 | CREDIT_CARD_SERVICING_VALIDATE | CARD_SERVICING | `Rediferir tarjeta {id} monto {N} cuotas {K} moneda {CCY}` |
| P11 | CREDIT_CARD_SERVICING_VALIDATE | CARD_SERVICING | `Avance tarjeta {id} monto {N} moneda {CCY}` |

## Fases mutantes

| Phase | requires_confirmation | next_action | Quien emite |
|-------|----------------------|-------------|-------------|
| ANALYZE | false | review_or_validate | Cognitiva (opcional) |
| VALIDATE | true | await_confirmation | Cognitiva (default) |
| EXECUTE | false | execute_operation | Solo dev/test (`GENESIS_ENV!=prod`) |

## Extensiones cognitivas (en envelope)

`scope_level`, `product_family`, `product_group`, `product_subtype`, `nature`, `phase`, `category`, `simulated`

## Sandbox

- `simulated=true`: customer_id CUST001..CUST010. Orquestador NO ejecuta Core.
- `simulated=false`: refs externas/reales.

## Ejemplos

### CUST001

```
Consulta portafolio
Consulta portafolio activo
Consulta saldo cuenta AHO001
Consulta cuenta corriente COR001
Consulta cdt CDT001
Consulta tarjeta TC001
Consulta prestamo PRE001
Consulta cuota prestamo PRE001V
Dispara movimiento cuenta origen COR001 a cuenta destino AHO001 valor 500 moneda DOP
Paga prestamo PRE001 valor 14500 moneda DOP
Abono capital prestamo PRE001 valor 50000 moneda DOP regla reducir_plazo
Rediferir tarjeta TC001 monto 200000 cuotas 12 moneda DOP
Avance tarjeta TC001 monto 50000 moneda DOP
```

### Externo/DEV

```
Consulta saldo cuenta 788337
Simula prestamo tipo VEHICLE monto 500000 plazo 48 moneda DOP
Rastrea transferencia REF12345
Dispara movimiento cuenta origen 13081221 a cuenta destino 2039083 valor 55500 moneda DOP
Paga prestamo 2333738 valor 239 moneda DOP
```

## Setear entorno

```powershell
$env:GENESIS_ENV = "dev"   # EXECUTE permitido
$env:GENESIS_ENV = "prod"  # EXECUTE bloqueado (403)
```

Consultar: `GET /config` → `{"genesis_env": "dev", "allow_cognitive_execute": true}`
