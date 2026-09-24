"""Catálogo de hechos Core → snapshot → respuesta de negocio.

Fuente: Documentacion_API_Productos (GET /products/v1/get-products-by-customer-id).
Regla dura: la IA NUNCA inventa montos/fechas; solo usa estos mapeos.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoreFactSpec:
    """Un hecho de negocio consultable."""

    fact_id: str
    product_category: str  # CA|CC|TC|PR|CD
    api_field: str
    snapshot_path: str
    client_label: str
    notes: str
    available_in_core: bool = True


# Semántica oficial por categoría (casos de uso API)
CORE_SEMANTICS: dict[str, str] = {
    "CA.availableBalance": "Saldo disponible de la cuenta",
    "CA.currentBalance": "Saldo actual (suele igualar disponible)",
    "CC.availableBalance": "Saldo disponible de la cuenta corriente",
    "CC.currentBalance": "Saldo actual",
    "TC.availableBalance": "Límite de crédito TOTAL (NO es disponible para compras)",
    "TC.currentBalance": "Monto total adeudado",
    "TC.availablePurchasesDomestic": "Crédito disponible para compras en DOP",
    "TC.availablePurchasesForeign": "Crédito disponible para compras en USD",
    "TC.minimumPaymentTcRd": "Pago mínimo DOP del estado de cuenta",
    "TC.statementCutoffDay": "Día de corte mensual",
    "TC.statementBalanceTcRd": "Saldo del último estado de cuenta DOP",
    "TC.cardExpiryDate": "Vencimiento del plástico (YYYYMM → MM/YY)",
    "TC.maturityDate": "Fecha límite de pago (Core la envía en maturityDate; no es vencimiento del plástico)",
    "CD.currentBalance": "Capital invertido del certificado",
    "CD.interestRateCd": "Tasa anual pactada (%)",
    "CD.interestAmountCd": "Intereses acumulados",
    "CD.maturityDate": "Fecha de vencimiento del certificado",
    "PR.availableBalance": "Monto original / desembolsado del préstamo",
    "PR.currentBalance": "Capital pendiente",
    "PR.domesticCurrencyBalance": "Total adeudado (capital + intereses)",
    "PR.pendingBalancePr": "Mora / cuotas vencidas (NO es la cuota contractual)",
    "PR.interestRatePr": "Tasa anual del préstamo (%)",
    "PR.nextPaymentDatePr": "Próxima fecha de pago",
    "PR.nextInstallmentDatePr": "Fecha de próxima cuota (alternativa)",
    "PR.maturityDate": "Vencimiento final del préstamo",
}

# Hechos que el cliente pregunta → campo real
FACT_CATALOG: tuple[CoreFactSpec, ...] = (
    CoreFactSpec(
        "account_available", "CA/CC", "availableBalance",
        "ProductSnapshot.available_balance", "saldo disponible",
        "Usar para 'cuánto tengo' / saldo de cuenta.",
    ),
    CoreFactSpec(
        "card_owed", "TC", "currentBalance",
        "ProductSnapshot.ledger_balance", "saldo adeudado",
        "Adeudo total de la tarjeta.",
    ),
    CoreFactSpec(
        "card_available", "TC", "availablePurchasesDomestic",
        "ProductSnapshot.available_purchases_domestic|available_balance",
        "crédito disponible",
        "NO usar availableBalance del API (ese es el límite).",
    ),
    CoreFactSpec(
        "card_limit", "TC", "availableBalance",
        "ProductSnapshot.credit_limit", "límite de crédito",
        "Límite total; distinto del disponible.",
    ),
    CoreFactSpec(
        "card_min_payment", "TC", "minimumPaymentTcRd",
        "ProductSnapshot.min_payment_rd", "pago mínimo",
        "0 en API = ausente / no aplica.",
    ),
    CoreFactSpec(
        "card_cutoff", "TC", "statementCutoffDay",
        "ProductSnapshot.cutoff_day", "fecha de corte (día)",
        "Solo día del mes; no es fecha límite de pago.",
    ),
    CoreFactSpec(
        "card_payment_due", "TC", "paymentDueDateTc|maturityDate",
        "ProductSnapshot.payment_due_date", "fecha límite de pago",
        "Core suele enviar la fecha de pago en maturityDate cuando falta paymentDueDateTc.",
    ),
    CoreFactSpec(
        "card_expiry", "TC", "cardExpiryDate",
        "ProductSnapshot.card_expiry", "vencimiento de la tarjeta",
        "YYYYMM → MM/YY. Distinto de la fecha de pago.",
    ),
    CoreFactSpec(
        "loan_principal", "PR", "currentBalance",
        "LoanSnapshot.outstanding_principal", "capital pendiente",
        "Capital por pagar.",
    ),
    CoreFactSpec(
        "loan_payoff", "PR", "domesticCurrencyBalance",
        "LoanSnapshot.payoff_amount", "total adeudado",
        "Capital + intereses cuando difiere del capital.",
    ),
    CoreFactSpec(
        "loan_overdue", "PR", "pendingBalancePr",
        "LoanSnapshot.overdue_amount", "mora",
        "NUNCA presentarlo como cuota contractual.",
    ),
    CoreFactSpec(
        "loan_rate", "PR", "interestRatePr",
        "LoanSnapshot.annual_interest_rate", "tasa anual",
        "",
    ),
    CoreFactSpec(
        "loan_next_due", "PR", "nextPaymentDatePr|nextInstallmentDatePr",
        "LoanSnapshot.next_due_date", "próxima fecha de pago",
        "Responde 'cuándo'; no 'cuánto'.",
    ),
    CoreFactSpec(
        "loan_maturity", "PR", "maturityDate",
        "LoanSnapshot.maturity_date", "vencimiento del préstamo",
        "Fin del plazo; distinto de próxima cuota.",
    ),
    CoreFactSpec(
        "loan_installment_amount", "PR", "(no enviado por API portafolio)",
        "LoanSnapshot.installment_amount", "monto de la cuota",
        "Core portafolio NO trae cuota contractual → siempre declarar no disponible.",
        available_in_core=False,
    ),
    CoreFactSpec(
        "dap_capital", "CD", "currentBalance|availableBalance",
        "ProductSnapshot.ledger_balance|available_balance", "capital invertido",
        "",
    ),
    CoreFactSpec(
        "dap_rate", "CD", "interestRateCd",
        "ProductSnapshot.interest_rate", "tasa del certificado",
        "",
    ),
    CoreFactSpec(
        "dap_interest", "CD", "interestAmountCd",
        "ProductSnapshot.interest_amount", "intereses acumulados",
        "",
    ),
    CoreFactSpec(
        "dap_maturity", "CD", "maturityDate",
        "ProductSnapshot.maturity_date", "vencimiento del certificado",
        "",
    ),
)

# Campos que NUNCA deben usarse para cierta pregunta
FORBIDDEN_SUBSTITUTIONS: dict[str, tuple[str, ...]] = {
    "loan_installment_amount": ("pendingBalancePr", "overdue_amount", "next_due_date"),
    "card_available": ("availableBalance_as_available",),  # límite ≠ disponible
    "loan_next_due": ("maturityDate",),  # vencimiento final ≠ próxima cuota
}


def fact_by_id(fact_id: str) -> CoreFactSpec | None:
    for f in FACT_CATALOG:
        if f.fact_id == fact_id:
            return f
    return None
