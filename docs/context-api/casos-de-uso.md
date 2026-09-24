# Casos de uso — semántica por producto

Reglas que el orquestador y los templates de respuesta deben respetar
para no alucinar significados de saldo.

| Tipo | Código | Regla / uso |
|------|--------|-------------|
| Cuenta de Ahorros | CA | Mostrar availableBalance como saldo disponible. |
| Cuenta de Ahorros | CA | maturityDate es siempre null (no tienen vencimiento). |
| Cuenta de Ahorros | CA | interestRateCd e interestAmountCd son 0. |
| Cuenta de Ahorros | CA | multiCurrency típicamente "0". |
| Certificado de Depósito | CD | Mostrar maturityDate como fecha de vencimiento. |
| Certificado de Depósito | CD | Mostrar interestRateCd como tasa pactada e interestAmountCd como intereses acumulados. |
| Certificado de Depósito | CD | availableBalance = currentBalance = capital invertido. |
| Certificado de Depósito | CD | No tienen maskedCardNumber. |
| Tarjeta de Crédito | TC | availableBalance = límite de crédito total. |
| Tarjeta de Crédito | TC | currentBalance = monto total adeudado. |
| Tarjeta de Crédito | TC | domesticCurrencyBalance = porción adeudada en DOP; puede ser negativo si hay créditos. |
| Tarjeta de Crédito | TC | foreignCurrencyBalance = porción adeudada en USD. |
| Tarjeta de Crédito | TC | availablePurchasesDomestic + availablePurchasesForeign = crédito disponible por moneda. |
| Tarjeta de Crédito | TC | maskedCardNumber identifica visualmente la tarjeta. |
| Tarjeta de Crédito | TC | cardExpiryDate en YYYYMM; mostrar como MM/YY. |
| Tarjeta de Crédito | TC | statementCutoffDay indica el día de corte mensual. |
| Tarjeta de Crédito | TC | minimumPaymentTcRd / minimumPaymentTcUs = pago mínimo del último estado de cuenta. |
| Tarjeta de Crédito | TC | statementBalanceTcRd / statementBalanceTcUs = balance del último estado de cuenta. |
| Tarjeta de Crédito | TC | Si multiCurrency = "1", acepta cargos en DOP y USD por separado. |
| Préstamo | PR | availableBalance = monto original aprobado del préstamo. |
| Préstamo | PR | currentBalance = capital pendiente por pagar. |
| Préstamo | PR | domesticCurrencyBalance = saldo total adeudado incluyendo intereses acumulados. |
| Préstamo | PR | pendingBalancePr = cuota(s) vencida(s) pendiente(s) de pago. |
| Préstamo | PR | interestRatePr = tasa de interés anual pactada. |
| Préstamo | PR | nextInstallmentDatePr y nextPaymentDatePr = fechas próximas de pago. |
| Préstamo | PR | maturityDate = fecha de vencimiento del préstamo (fin del plazo). |
