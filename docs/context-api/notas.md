# Notas operativas

1. availablePurchasesForeign y availablePurchasesDomestic solo aparecen en productos TC; no están presentes en CA, CD ni PR.
2. Todos los campos numéricos de saldo retornan 0 (no null) cuando no aplican al tipo de producto.
3. Los campos de fecha retornan null cuando no aplican, por ejemplo maturityDate en cuentas de ahorro y nextInstallmentDatePr en productos que no son préstamos.
4. foreignCurrencyBalance y domesticCurrencyBalance pueden ser iguales en productos de moneda única.
5. En tarjetas de crédito, domesticCurrencyBalance negativo indica que el banco tiene un saldo a favor del cliente (crédito aplicado).
