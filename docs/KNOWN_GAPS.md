# Gaps documentados — Capa Cognitiva Demo

## 1. ~~Sin balance_amount en snapshot de cuentas~~ RESUELTO

**Estado**: ✅ Resuelto en demo (SQLite simula Redis/Core).

**Descripción**: `ProductSnapshot` ahora incluye `available_balance` y `ledger_balance`
cargados desde la tabla `accounts` de SQLite (JOIN con products). Cuentas CHECKING, 
SAVINGS y PAYROLL tienen saldos reales.

**Implementación**:
- `ProductSnapshot` extendido con `available_balance: Decimal | None` y `ledger_balance: Decimal | None`
- `SqliteCustomerContextLoader` hace LEFT JOIN con `accounts` table
- `client_response` para ACCOUNT_BALANCE_READ muestra el monto cuando disponible
- Feasibility check: compara balance de cuenta vs cuota de préstamo

**Nota**: En producción, los saldos vendrían del Core vía Redis snapshot (directriz 90).
En demo, SQLite simula ese snapshot.

---

## 2. Sin historial de pagos realizados en loan_detail

**Estado**: Documentado, mitigado con prompt 1.1.0.

**Descripción**: `LoanSnapshot` contiene datos del estado actual del préstamo:
- installment_amount, annual_interest_rate, outstanding_principal
- delinquency_days, next_due_date, loan_type

**NO contiene**:
- Fecha del último pago realizado
- Monto del último pago
- Historial de pagos
- Fecha de desembolso
- Monto original del préstamo

**Mitigación**: Prompt final-response 1.1.0 incluye regla explícita:
> "Si el dato preguntado NO existe en loan_detail → responder: 'Ese dato no está 
> disponible en este momento. Puedo ayudarte con cuota, tasa, capital pendiente o 
> próxima fecha de pago.'"

**Resolución futura**: HistoricalActivityProvider (directiva 164-167) como herramienta 
bajo demanda para consultas de actividad histórica.

---

## 3. Productos USD excluidos del portfolio visible

**Estado**: Documentado, decisión de diseño.

**Descripción**: El portfolio se filtra por `currency == customer.default_currency` (DOP).
Productos en USD (ej: AHO001USD "Ahorro dólares viaje") no aparecen en la lista visible 
para el modelo ni en PORTFOLIO_LIST.

**Razón**: Directrices 236-241 establecen que operaciones entre monedas diferentes 
requieren capacidad transaccional independiente con cotización de cambio.

**Impacto**: Si un usuario pregunta "saldo de mi ahorro en dólares", no encontrará 
el producto en el portfolio filtrado.

**Resolución futura**: Incluir productos USD con indicador `cross_currency=true` en 
portfolio y manejar mediante capacidad específica cuando se implemente.

---

Fecha: 2026-07-29
Versión: 1.0

---

## 4. Token usage no disponible en decision_trace

**Estado**: Documentado, no bloqueante.

**Descripción**: El SDK de Microsoft Agent Framework (`agent_framework.openai.OpenAIChatCompletionClient`)
no expone `usage` (prompt_tokens, completion_tokens) en el objeto de respuesta accesible
desde `Agent.run()`. El response value es solo el structured output parseado.

**Impacto**:
- `decision_trace` incluye `duration_ms` por step pero NO `tokens_in` / `tokens_out`.
- No se puede hacer correlación tokens vs latencia por invocación.
- El reporte e2e_100_varied.py muestra latencia pero no tokens.

**Mitigación actual**:
- `duration_ms` por step (capa0, capa1, proposer, verifier, final_response)
- `total_request_ms` en el response body

**Resolución futura**: 
- Interceptar la respuesta HTTP raw de Azure OpenAI antes de que el SDK la parsee
  (middleware o wrapper del ChatCompletionClient).
- O migrar a Azure OpenAI SDK directo que expone `response.usage`.
- O usar Azure Monitor / Application Insights para métricas de consumo por deployment.

---

Fecha actualización: 2026-07-29
