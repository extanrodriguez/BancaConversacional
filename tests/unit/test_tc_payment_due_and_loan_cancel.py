"""Fixes guía QA: fecha pago/expiración TC + cancelar el préstamo (proceso)."""

from __future__ import annotations

from decimal import Decimal

from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
from genesis_cognitive.context.core_portfolio_mapper import map_core_portfolio
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.router.field_guardrails import is_compound_personal_query
from genesis_cognitive.router.final_response_agent import (
    _build_card_multi_field_parts,
    build_card_detail_response,
)


def _tc_snap(*, due: str | None = "2026-09-03", expiry: str | None = "04/27") -> ProductSnapshot:
    return ProductSnapshot(
        product_id="TC6374",
        product_type="CREDIT_CARD",
        alias="Credito Joven Empleado",
        currency="DOP",
        status="active",
        card_mask="****6374",
        credit_limit=Decimal("50000"),
        ledger_balance=Decimal("34529"),
        available_balance=Decimal("15471"),
        cutoff_day=8,
        payment_due_date=due,
        card_expiry=expiry,
    )


def test_guia_q3_compound_detects_colloquial_debt_and_due() -> None:
    q = "cuanto e k debo d la tarjeta y cuando me toca pagar"
    assert is_compound_personal_query(q)
    parts = _build_card_multi_field_parts(q, _tc_snap(), "Credito Joven Empleado (****6374)")
    joined = " ".join(parts).lower()
    assert "34529" in joined.replace(",", "") or "34,529" in joined or "adeudado" in joined
    assert "2026-09-03" in joined
    assert "corte" not in joined or "límite de pago" in joined or "fecha límite" in joined


def test_card_due_from_payment_due_date_not_cutoff_fallback() -> None:
    text = build_card_detail_response(
        "cuando me toca pagar",
        _tc_snap(),
        "usuario 1",
        "Credito Joven Empleado (****6374)",
    )
    low = text.lower()
    assert "2026-09-03" in text
    assert "fecha límite" in low or "fecha limite" in low
    assert "no tengo la fecha" not in low


def test_card_expiry_expira_uses_card_expiry() -> None:
    text = build_card_detail_response(
        "cuando expira mi tarjeta",
        _tc_snap(),
        "usuario 1",
        "Credito Joven Empleado (****6374)",
    )
    assert "04/27" in text
    assert "2026-09-03" not in text


def test_mapper_core_sample_tc_payment_and_expiry() -> None:
    mapped = map_core_portfolio(
        {
            "isSucceded": True,
            "data": [
                {
                    "productCategory": "TC",
                    "productIdentification": "220709213940583959",
                    "productDescription": "Credito Joven Empleado",
                    "currencyCode": "214",
                    "productStatus": "1",
                    "availableBalance": 50000,
                    "maturityDate": "2026-09-03 00:00:00",
                    "currentBalance": 34529,
                    "maskedCardNumber": "****6374",
                    "statementCutoffDay": 8,
                    "cardExpiryDate": 202704,
                    "availablePurchasesDomestic": 15471,
                }
            ],
        }
    )
    tc = mapped.snapshot.products[0]
    assert tc.payment_due_date == "2026-09-03"
    assert tc.card_expiry == "04/27"
    assert tc.maturity_date is None


def test_cancelar_el_prestamo_routes_to_loan_cancellation_process() -> None:
    snap = CustomerContextSnapshot(
        customer_id="C1",
        display_name="Cliente",
        default_currency="DOP",
        products=(),
        loans=(
            LoanSnapshot(
                product_id="320658",
                loan_type="Préstamo",
                installment_amount=Decimal("0"),
                annual_interest_rate=Decimal("10"),
                outstanding_principal=Decimal("412282.54"),
                delinquency_days=0,
                next_due_date="2026-08-25",
            ),
        ),
    )
    for q in (
        "cancelar el prestamo",
        "cancelar el préstamo",
        "cancelar prestamo",
        "quiero cancelar el préstamo",
    ):
        plan = interpret_turn_plan(q, None, snapshot=snap)
        process = [t for t in plan.tasks if t.domain == "process" and t.object == "loan_cancellation"]
        assert process, f"expected loan_cancellation for: {q!r} → {[ (t.domain, t.object, t.action) for t in plan.tasks ]}"


def test_cancelar_mi_prestamo_with_amount_stays_personal_payoff() -> None:
    """No romper payoff personal: «cuánto para cancelar mi préstamo»."""
    snap = CustomerContextSnapshot(
        customer_id="C1",
        display_name="Cliente",
        default_currency="DOP",
        products=(),
        loans=(
            LoanSnapshot(
                product_id="320658",
                loan_type="Préstamo",
                installment_amount=Decimal("0"),
                annual_interest_rate=Decimal("10"),
                outstanding_principal=Decimal("412282.54"),
                delinquency_days=0,
                next_due_date="2026-08-25",
            ),
        ),
    )
    plan = interpret_turn_plan(
        "cuánto necesito para cancelar mi préstamo",
        None,
        snapshot=snap,
    )
    # Debe existir lectura personal de payoff, no solo proceso KB
    personal = [
        t for t in plan.tasks
        if t.domain == "personal" and "payoff" in (t.fields or [])
    ]
    assert personal or any(
        t.domain == "personal" and t.object == "loan" for t in plan.tasks
    )
