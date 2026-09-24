# Diccionario de campos — API Productos

Relación campo → significado → uso en la banca conversacional.

| Sección | Campo | Tipo | Aplica a | Descripción |
|---------|-------|------|----------|-------------|
| Identificación y clasificación | `productCategory` | string | Todos | Categoría del producto. Ver tabla de categorías. |
| Identificación y clasificación | `productIdentification` | string | Todos | Número identificador único del producto (cuenta, tarjeta enmascarada o préstamo). |
| Identificación y clasificación | `productDescription` | string | Todos | Nombre descriptivo del producto (ej. "Cuenta de Ahorros", "Certificado de Depósito", "Visa Infinite"). |
| Identificación y clasificación | `productStatus` | string | Todos | Estado del producto. Ver tabla de estados. |
| Identificación y clasificación | `currencyCode` | string | Todos | Código de moneda ISO 4217 numérico. "214" = DOP; "840" = USD. |
| Identificación y clasificación | `partyType` | string \| null | Todos | Tipo de titular del producto. Puede ser null si no aplica. |
| Balances generales | `availableBalance` | number | Todos | Saldo disponible. En TC representa límite total; en PR, monto original del préstamo. |
| Balances generales | `currentBalance` | number | Todos | Saldo actual. En TC es monto utilizado/adeudado; en cuentas es igual al saldo disponible. |
| Balances generales | `foreignCurrencyBalance` | number | Todos | Saldo expresado en moneda extranjera (USD). |
| Balances generales | `domesticCurrencyBalance` | number | Todos | Saldo expresado en moneda local (DOP). En TC puede ser negativo cuando hay créditos aplicados. |
| Balances generales | `multiCurrency` | string | Todos | Indica si maneja múltiples monedas. "0" = moneda única; "1" = multimoneda. |
| Tarjeta de Crédito | `maskedCardNumber` | string \| null | TC | Número de tarjeta enmascarado (ej. "****5778"). null en otros productos. |
| Tarjeta de Crédito | `cardExpiryDate` | number | TC | Fecha de vencimiento en formato YYYYMM. 0 si no aplica. |
| Tarjeta de Crédito | `statementCutoffDay` | number | TC | Día del mes del corte del estado de cuenta. 0 si no aplica. |
| Tarjeta de Crédito | `availablePurchasesForeign` | number | TC | Monto disponible para compras en moneda extranjera (USD). Solo en tarjetas multimoneda. |
| Tarjeta de Crédito | `availablePurchasesDomestic` | number | TC | Monto disponible para compras en moneda local (DOP). |
| Tarjeta de Crédito | `minimumPaymentTcRd` | number | TC | Pago mínimo del estado de cuenta en DOP. 0 si no hay pago pendiente o no aplica. |
| Tarjeta de Crédito | `minimumPaymentTcUs` | number | TC | Pago mínimo del estado de cuenta en USD. 0 si no hay pago pendiente o no aplica. |
| Tarjeta de Crédito | `statementBalanceTcRd` | number | TC | Saldo del último estado de cuenta en DOP. 0 si no aplica. |
| Tarjeta de Crédito | `statementBalanceTcUs` | number | TC | Saldo del último estado de cuenta en USD. 0 si no aplica. |
| Certificado de Depósito | `maturityDate` | string \| null | CD / PR | Fecha de vencimiento en formato YYYY-MM-DD HH:mm:ss. null cuando no aplica. |
| Certificado de Depósito | `interestRateCd` | number | CD | Tasa de interés anual del certificado (%). 0 si no aplica. |
| Certificado de Depósito | `interestAmountCd` | number | CD | Intereses acumulados del certificado en la moneda del producto. 0 si no aplica. |
| Préstamo | `pendingBalancePr` | number | PR | Saldo pendiente o cuota en mora. 0 si no hay monto vencido. |
| Préstamo | `interestRatePr` | number | PR | Tasa de interés anual del préstamo (%). 0 si no aplica. |
| Préstamo | `nextInstallmentDatePr` | string \| null | PR | Fecha de la próxima cuota en formato YYYY-MM-DD HH:mm:ss. null si no aplica. |
| Préstamo | `nextPaymentDatePr` | string \| null | PR | Fecha del próximo pago en formato YYYY-MM-DD HH:mm:ss. null si no aplica. |

## Mapeo a CustomerContextSnapshot

| Campo API | Snapshot | Notas |
|-----------|----------|-------|
| `productCategory` | `product_type` | CA→SAVINGS, CC→CHECKING, CD→TERM_DEPOSIT, TC→CREDIT_CARD, PR→LOAN |
| `productIdentification` | `product_id` | Identificador único |
| `productDescription` | `alias` | Nombre visible |
| `productStatus` | `status` | 1/3 activos según reglas Core |
| `currencyCode` | `currency` | 214→DOP, 840→USD |
| `availableBalance` | `available_balance` / `credit_limit` | Semántica por categoría |
| `currentBalance` | `ledger_balance` | Adeudo TC / saldo cuenta |
| `maskedCardNumber` | `card_mask` | Solo TC |
| `pendingBalancePr` | `LoanSnapshot.overdue_amount` | Mora, no cuota contractual |
