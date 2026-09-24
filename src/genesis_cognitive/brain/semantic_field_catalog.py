"""Catálogo semántico de campos por tipo de producto (capa cognitiva).

Fuente: snapshot/adaptadores reales. No inventa capacidades Core.
Convenciones documentadas (no son frases admitidas cerradas):
- CREDIT_CARD «saldo» sin calificar → deuda actual (ledger_balance).
- CREDIT_CARD «disponible» → available_purchases / available_balance.
- ACCOUNT «saldo» / «saldo actual» → ledger; «disponible» → available.
"""

from __future__ import annotations

from typing import Any

# Campo semántico → atributo(s) del ProductSnapshot / LoanSnapshot
FIELD_SOURCES: dict[str, dict[str, Any]] = {
    "available": {
        "label": "disponible",
        "types": ("SAVINGS", "CHECKING", "PAYROLL", "CREDIT_CARD"),
        "snapshot_attr": "available_balance",
        "absent_ok": True,
    },
    "balance": {
        "label": "saldo_actual_o_deuda",
        "types": ("SAVINGS", "CHECKING", "PAYROLL", "CREDIT_CARD"),
        "snapshot_attr": "ledger_balance",
        "card_convention": "debt",
        "absent_ok": True,
    },
    "min_payment": {
        "label": "pago_minimo",
        "types": ("CREDIT_CARD",),
        "snapshot_attr": "min_payment_rd",
        "absent_ok": True,
    },
    "due_date": {
        "label": "fecha_limite_pago",
        "types": ("CREDIT_CARD", "LOAN"),
        "loan_attr": "next_due_date",
        "absent_ok": True,
    },
    "rate": {
        "label": "tasa",
        "types": ("LOAN", "TERM_DEPOSIT", "CREDIT_CARD"),
        "snapshot_attr": "interest_rate",
        "loan_attr": "annual_interest_rate",
        "absent_ok": True,
    },
    "principal": {
        "label": "capital_pendiente",
        "types": ("LOAN",),
        "loan_attr": "outstanding_principal",
        "absent_ok": True,
    },
    "payoff": {
        "label": "saldo_cancelacion",
        "types": ("LOAN",),
        "loan_attr": "payoff_amount",
        "absent_ok": True,
    },
    "maturity": {
        "label": "vencimiento",
        "types": ("TERM_DEPOSIT", "LOAN"),
        "snapshot_attr": "maturity_date",
        "loan_attr": "maturity_date",
        "absent_ok": True,
    },
    "interest_amount": {
        "label": "intereses_generados",
        "types": ("TERM_DEPOSIT",),
        "snapshot_attr": "interest_amount",
        "absent_ok": True,
    },
}


def applicable_fields_for_type(product_type: str) -> tuple[str, ...]:
    pt = str(product_type or "").upper()
    return tuple(sorted(k for k, meta in FIELD_SOURCES.items() if pt in meta["types"]))


def field_availability(product: Any, field: str) -> str:
    """available | absent | unsupported."""
    meta = FIELD_SOURCES.get(field)
    if meta is None:
        return "unsupported"
    pt = str(getattr(product, "product_type", "") or "").upper()
    if pt not in meta["types"]:
        return "unsupported"
    if "snapshot_attr" in meta:
        val = getattr(product, meta["snapshot_attr"], None)
        if val is not None:
            return "available"
    if "loan_attr" in meta and pt == "LOAN":
        # Loan fields live on CustomerContextSnapshot.loans
        return "absent"  # caller puede enriquecer con loan
    if meta.get("absent_ok"):
        return "absent"
    return "unsupported"


def card_saldo_convention() -> str:
    """Convención documentada para «saldo» de tarjeta sin calificar."""
    return "debt"


def build_capability_map() -> dict[str, Any]:
    return {
        "version": "contextual-v1",
        "fields": FIELD_SOURCES,
        "conventions": {
            "credit_card.saldo_unqualified": "ledger_balance (deuda actual)",
            "credit_card.disponible": "available_balance",
            "account.saldo_actual": "ledger_balance",
            "account.disponible": "available_balance",
        },
    }
