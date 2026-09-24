"""Consulta pendiente estructurada para selecciones de producto."""

from __future__ import annotations

import unicodedata
from typing import Any


def _norm(text: str) -> str:
    value = "".join(
        char
        for char in unicodedata.normalize("NFD", (text or "").lower())
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(value.split())


def build_query_spec(question: str, intent_id: str | None = None) -> dict[str, str]:
    """Convierte la pregunta libre en el campo que debe sobrevivir a la selección."""
    q = _norm(question)
    field = "detail"

    if any(term in q for term in ("movimiento", "transaccion", "consumo")):
        field = "movements"
    elif any(term in q for term in ("fecha limite", "limite de pago", "cuando debo pagar", "cuando me toca", "me toca pagar")):
        field = "payment_due_date"
    elif any(term in q for term in ("fecha de corte", "dia de corte", "cuando corta")):
        field = "cutoff_date"
    elif any(term in q for term in ("fecha de pago", "proximo pago", "cuando pago", "cuando es mi")):
        field = "payment_due_date"
    elif any(term in q for term in ("expira", "expiracion", "vence mi tarjeta")):
        field = "card_expiry"
    elif any(term in q for term in ("vencimiento", "cuando vence", "fecha de vencimiento")):
        field = "maturity_date"
    elif "tasa" in q or "interes anual" in q:
        field = "rate"
    elif any(term in q for term in ("pago minimo", "minimo a pagar")):
        field = "minimum_payment"
    elif any(term in q for term in ("limite de credito", "cupo", "linea de credito")):
        field = "credit_limit"
    elif any(term in q for term in ("disponible", "cuanto tengo")):
        field = "available_balance"
    elif any(term in q for term in ("cuota", "mensualidad", "letra")):
        field = "installment_amount"
    elif any(term in q for term in ("mora", "atraso", "vencido")):
        field = "overdue"
    elif any(term in q for term in ("saldar", "cancelar prestamo", "payoff")):
        field = "payoff_amount"
    elif any(term in q for term in ("capital", "principal")):
        field = "principal"
    elif any(term in q for term in ("saldo", "cuanto debo", "adeud")):
        field = "balance"

    return {
        "field": field,
        "scope": "single",
        "response_shape": "field" if field != "detail" else "detail",
        "intent_id": intent_id or "",
    }


_CANONICAL_QUESTION = {
    "movements": "muéstrame los movimientos de este producto",
    "payment_due_date": "cuál es la fecha límite de pago de este producto",
    "cutoff_date": "cuál es la fecha de corte de este producto",
    "maturity_date": "cuál es la fecha de vencimiento de este producto",
    "card_expiry": "cuál es la fecha de vencimiento de esta tarjeta",
    "rate": "cuál es la tasa de este producto",
    "minimum_payment": "cuál es el pago mínimo de este producto",
    "credit_limit": "cuál es el límite de crédito de este producto",
    "available_balance": "cuál es el saldo disponible de este producto",
    "installment_amount": "cuánto es la cuota de este producto",
    "overdue": "cuál es la mora de este producto",
    "payoff_amount": "cuánto necesito para saldar este producto",
    "principal": "cuál es el capital pendiente de este producto",
    "balance": "cuál es el saldo de este producto",
    "detail": "dame información de este producto",
}


def query_question(spec: dict[str, Any] | None, fallback: str) -> str:
    field = str((spec or {}).get("field") or "")
    return _CANONICAL_QUESTION.get(field) or fallback
