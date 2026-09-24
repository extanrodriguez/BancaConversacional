"""Ventana temporal de pago próximo: pasado / hoy / futuro."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.upcoming_payment_window import (
    classify_due_date,
    resolve_payment_window,
)
from genesis_cognitive.router.field_guardrails import apply_upcoming_payments_guardrail


def _snap(*, loan_due: str, card_due: str | None = None) -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id="726588",
        display_name="Felix",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="LOAN1",
                product_type="LOAN",
                alias="Prestamo Personal",
                currency="DOP",
                status="active",
                last_four="0658",
            ),
            ProductSnapshot(
                product_id="TC1",
                product_type="CREDIT_CARD",
                alias="Visa Demo",
                currency="DOP",
                status="active",
                card_mask="****1234",
                payment_due_date=card_due,
                min_payment_rd=Decimal("500"),
            ),
        ),
        loans=(
            LoanSnapshot(
                product_id="LOAN1",
                loan_type="PERSONAL",
                outstanding_principal=Decimal("100000"),
                next_due_date=loan_due,
                installment_amount=Decimal("1000"),
                payoff_amount=Decimal("100000"),
                annual_interest_rate=Decimal("12"),
                delinquency_days=0,
                last_four="0658",
            ),
        ),
    )


def test_window_classifies_past_today_future():
    window = resolve_payment_window(
        reference=date(2026, 9, 20),
        timezone="America/Santo_Domingo",
        window_days=30,
    )
    assert classify_due_date(date(2026, 8, 1), window) == "overdue"
    assert classify_due_date(date(2026, 9, 20), window) == "upcoming"
    assert classify_due_date(date(2026, 10, 5), window) == "upcoming"
    assert classify_due_date(date(2026, 11, 1), window) == "beyond"


def test_guardrail_past_date_is_not_upcoming():
    snap = _snap(loan_due="2026-08-01", card_due="2026-11-15")
    hit = apply_upcoming_payments_guardrail(
        snap,
        "Tengo algun prestamo o tarjeta con un pago proximo?",
        reference_date="2026-09-20",
        window_days=30,
        timezone="America/Santo_Domingo",
    )
    assert hit is not None
    text = hit[2] or ""
    low = text.lower()
    assert "america/santo_domingo" in low
    assert "2026-09-20" in text
    assert "ventana temporal" in low
    assert "no es pago próximo" in low or "no es pago proximo" in low
    assert "2026-08-01" in text
    # Fuera de ventana: no listar como pago próximo
    assert "pago próximo el **2026-08-01**" not in text
    assert "2026-11-15" in text


def test_guardrail_today_and_near_future_are_upcoming():
    snap = _snap(loan_due="2026-09-20", card_due="2026-10-05")
    hit = apply_upcoming_payments_guardrail(
        snap,
        "Tengo algun prestamo o tarjeta con un pago proximo?",
        reference_date="2026-09-20",
    )
    assert hit is not None
    text = hit[2] or ""
    assert "pago próximo el **2026-09-20**" in text
    assert "2026-10-05" in text
    assert "dentro de la ventana" in text.lower() or "pago próximo" in text.lower()
    action = (hit[1] or [{}])[0]
    assert action.get("payment_window", {}).get("payment_window_timezone") == "America/Santo_Domingo"
