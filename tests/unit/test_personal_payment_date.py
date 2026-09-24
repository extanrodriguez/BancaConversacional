"""Fecha de pago personal: respuesta corta y prioridad sobre FAQ/Foundry."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import PendingAction
from genesis_cognitive.router.field_guardrails import (
    apply_loan_fastpath_guardrail,
    is_personal_payment_date_question,
    run_field_fastpath,
)
from genesis_cognitive.router.final_response_agent import build_loan_detail_response
from genesis_cognitive.router.knowledge_followup import is_knowledge_followup
from genesis_cognitive.router.product_focus import (
    looks_like_product_option_selection,
    pending_field_question_for_selection,
)


def test_fecha_limite_mi_prestamo_is_personal() -> None:
    assert is_personal_payment_date_question("fecha limite de mi prestamo") is True
    assert is_personal_payment_date_question("cual es la fecha limite de pago") is True
    assert is_personal_payment_date_question("¿Qué es la fecha límite de pago?") is False


def test_fecha_limite_not_kb_followup() -> None:
    assert is_knowledge_followup("cual es la fecha limite de pago") is False
    assert is_knowledge_followup("fecha limite de mi prestamo") is False


def test_loan_detail_date_is_short_not_full_ficha() -> None:
    detail = {
        "product_id": "LOAN_7615",
        "mask": "7615",
        "installment_amount": "5000",
        "outstanding_principal": "185000",
        "annual_interest_rate": "12.5",
        "next_due_date": "2026-09-01",
        "maturity_date": "2028-09-01",
        "disbursed_amount": "200000",
    }
    text = build_loan_detail_response("fecha limite de mi prestamo", detail, "Felix")
    low = text.lower()
    assert "2026-09-01" in text
    assert "200,000" not in text and "200000" not in text.replace(",", "")
    assert "capital pendiente" not in low
    assert "monto original" not in low


def _snap_two_loans() -> CustomerContextSnapshot:
    p1 = ProductSnapshot(
        product_id="227615", product_type="LOAN", alias="Préstamo",
        currency="DOP", status="active", ledger_balance=Decimal("185000"),
    )
    p2 = ProductSnapshot(
        product_id="3214567890123", product_type="LOAN", alias="Préstamo",
        currency="DOP", status="active", ledger_balance=Decimal("478000"),
    )
    l1 = LoanSnapshot(
        product_id="227615", loan_type="PERSONAL",
        outstanding_principal=Decimal("185000"), disbursed_amount=Decimal("200000"),
        annual_interest_rate=Decimal("12.5"), next_due_date="2026-09-01",
        maturity_date="2028-09-01", installment_amount=Decimal("5000"),
        payoff_amount=Decimal("185000"), overdue_amount=Decimal("0"), delinquency_days=0,
    )
    l2 = LoanSnapshot(
        product_id="3214567890123", loan_type="PERSONAL",
        outstanding_principal=Decimal("478000"), disbursed_amount=Decimal("500000"),
        annual_interest_rate=Decimal("15"), next_due_date="2026-08-10",
        maturity_date="2027-08-10", installment_amount=Decimal("8000"),
        payoff_amount=Decimal("478000"), overdue_amount=Decimal("0"), delinquency_days=0,
    )
    return CustomerContextSnapshot(
        customer_id="323677", display_name="Felix Prestamos",
        default_currency="DOP", products=(p1, p2), loans=(l1, l2),
    )


def test_apk_card_selection_looks_like_option() -> None:
    assert looks_like_product_option_selection("Préstamo ...27615") is True
    assert looks_like_product_option_selection("fecha limite de mi prestamo") is False


def test_card_selection_after_payment_date_clarification_returns_only_date() -> None:
    """Tras clarificar con cards, elegir préstamo debe devolver solo la fecha (no ficha)."""
    snap = _snap_two_loans()
    pending = PendingAction(
        intent_id="PAYMENT_DATE_READ",
        capability_candidate="PRODUCT_FIELD",
        selected_route="PERSONAL_READ",
        detected_entities={"account_ref": None},
        missing_requirements=["account_ref"],
        suggested_question="¿Sobre cuál deseas consultar?",
        original_question="fecha limite de mi prestamo",
    )
    sess = SimpleNamespace(
        pending_action=pending, last_resolved=None, product_focus=None,
    )
    assert pending_field_question_for_selection(sess, "Préstamo ...27615") == (
        "fecha limite de mi prestamo"
    )
    out = apply_loan_fastpath_guardrail(
        snap, "Préstamo ...27615", session=sess,
    )
    assert out is not None
    text = out[2] or ""
    low = text.lower()
    assert "2026-09-01" in text
    assert "monto original" not in low
    assert "capital pendiente" not in low
    assert "tasa" not in low

    hit = run_field_fastpath(snap, "Préstamo ...27615", None, session=sess)
    assert hit is not None
    assert "2026-09-01" in (hit[2] or "")
    assert "monto original" not in (hit[2] or "").lower()


def test_dap_card_selection_keeps_tasa_not_kb_ambiguity() -> None:
    from genesis_cognitive.router.field_guardrails import apply_dap_field_guardrail

    snap = CustomerContextSnapshot(
        customer_id="U1",
        display_name="usuario 1",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="33012010005511", product_type="TERM_DEPOSIT",
                alias="Certificado de Depósito", currency="DOP", status="active",
                available_balance=Decimal("100000"), interest_rate=Decimal("7.5"),
            ),
            ProductSnapshot(
                product_id="33012010005809", product_type="TERM_DEPOSIT",
                alias="Certificado de Depósito", currency="DOP", status="active",
                available_balance=Decimal("200000"), interest_rate=Decimal("8.0"),
            ),
        ),
        loans=(),
    )
    pending = PendingAction(
        intent_id="TERM_DEPOSIT_DETAIL_READ",
        capability_candidate="TERM_DEPOSIT_DETAIL",
        selected_route="PERSONAL_READ",
        detected_entities={"account_ref": None},
        missing_requirements=["account_ref"],
        suggested_question="¿Cuál certificado?",
        original_question="Cual es la tasa de mi certificado?",
    )
    sess = SimpleNamespace(pending_action=pending, last_resolved=None, product_focus=None)
    msg = "Certificado de depósito (...05511) DEPOSITO_PLAZO_5511"
    hit = run_field_fastpath(snap, msg, None, session=sess)
    assert hit is not None
    text = (hit[2] or "").lower()
    assert "garantía" not in text and "garantia" not in text
    assert "definición" not in text and "definicion" not in text
    assert "7.5" in (hit[2] or "") or "tasa" in text
    assert "5511" in (hit[2] or "") or "05511" in (hit[2] or "")
    assert hit[4] != "kb_ambiguity"

    out = apply_dap_field_guardrail("VALID_CONTRACT", [], snap, msg, session=sess)
    assert out[0] == "VALID_CONTRACT"
    assert "7.5" in (out[2] or "")


def test_loan_rate_singular_and_plural_offer_contextual_cards() -> None:
    from genesis_cognitive.brain.azure_intent_brain import heuristic_intent
    from genesis_cognitive.brain.grounded_executor import execute_grounded

    snap = _snap_two_loans()

    singular = heuristic_intent("la tasa de mi prestamo")
    assert singular.product == "loan"
    assert singular.field == "rate"
    assert singular.scope == "single"
    one = execute_grounded(singular, snap, "la tasa de mi prestamo")
    assert one.status == "CLARIFICATION_REQUIRED"
    assert one.options and len(one.options) == 2

    plural = heuristic_intent("si la tasa de mis prestamos")
    assert plural.product == "loan"
    assert plural.field == "rate"
    assert plural.scope == "all"
    all_rates = execute_grounded(plural, snap, "si la tasa de mis prestamos")
    assert all_rates.status == "CLARIFICATION_REQUIRED"
    assert all_rates.options and len(all_rates.options) == 2
    assert all_rates.options[0]["context"]["field"] == "rate"
    assert "Tasa de interés:" in all_rates.options[0]["subtitle"]
    assert "Moneda: DOP" in all_rates.options[0]["subtitle"]


def test_loan_maturity_uses_selected_loan_context() -> None:
    snap = _snap_two_loans()
    last_resolved = SimpleNamespace(
        intent_id="LOAN_DETAIL_READ",
        account_ref="3214567890123",
        original_question="dame información de mi préstamo",
    )

    result = run_field_fastpath(
        snap,
        "cual es la fecha de vencimiento de mi prestamo",
        last_resolved,
    )

    assert result is not None
    assert result[0] == "VALID_CONTRACT"
    assert "2027-08-10" in result[2]
    assert "2028-09-01" not in result[2]

    next_payment = run_field_fastpath(
        snap,
        "cuando es el proximo pago de mi prestamo",
        last_resolved,
    )
    assert next_payment is not None
    assert "2026-08-10" in next_payment[2]
    assert "2026-09-01" not in next_payment[2]


def test_other_loan_selects_only_remaining_loan() -> None:
    snap = _snap_two_loans()
    last_resolved = SimpleNamespace(
        intent_id="LOAN_DETAIL_READ",
        account_ref="3214567890123",
        original_question="cuál es mi fecha de pago",
    )
    session = SimpleNamespace(
        last_resolved=last_resolved,
        product_focus=SimpleNamespace(
            kind="LOAN", product_id="3214567890123",
            intent_id="LOAN_DETAIL_READ", original_question="cuál es mi fecha de pago",
        ),
        pending_action=None,
        last_knowledge_topic="reclamaciones",
    )

    result = run_field_fastpath(
        snap,
        "y la fecha de pago de mi otro prestamo",
        last_resolved,
        session=session,
    )

    assert result is not None
    assert result[0] == "VALID_CONTRACT"
    assert result[6] == "227615"
    assert "2026-09-01" in result[2]
    assert "2026-08-10" not in result[2]


def test_other_loan_with_multiple_alternatives_requires_selection() -> None:
    snap = _snap_two_loans()
    third_product = ProductSnapshot(
        product_id="LOAN445566",
        product_type="LOAN",
        alias="Préstamo",
        currency="DOP",
        status="active",
    )
    third_loan = LoanSnapshot(
        product_id="LOAN445566",
        loan_type="PERSONAL",
        installment_amount=Decimal("4000"),
        annual_interest_rate=Decimal("11"),
        outstanding_principal=Decimal("90000"),
        delinquency_days=0,
        next_due_date="2026-09-20",
        maturity_date="2029-01-15",
    )
    snap = replace(
        snap,
        products=(*snap.products, third_product),
        loans=(*snap.loans, third_loan),
    )
    last_resolved = SimpleNamespace(
        intent_id="LOAN_DETAIL_READ",
        account_ref="3214567890123",
        original_question="cuál es mi fecha de pago",
    )

    result = run_field_fastpath(
        snap,
        "y la fecha de pago de mi otro prestamo",
        last_resolved,
    )

    assert result is not None
    assert result[0] == "CLARIFICATION_REQUIRED"
    assert result[3] and len(result[3]) == 2
    assert all(option["ref"] != "PRESTAMO_90123" for option in result[3])


def test_compound_card_query_not_payment_date_empty() -> None:
    from genesis_cognitive.router.field_guardrails import (
        is_compound_personal_query,
        is_personal_payment_date_question,
    )

    q = (
        "cuanto debo de mi tarjeta de credito, cuanto tengo disponible "
        "y cuando es mi fecha limite de pago?"
    )
    assert is_compound_personal_query(q) is True
    assert is_personal_payment_date_question(q) is False

    snap = CustomerContextSnapshot(
        customer_id="C1",
        display_name="Carlos",
        default_currency="DOP",
        products=(),
        loans=(),
    )
    hit = run_field_fastpath(snap, q, None)
    assert hit is not None
    low = (hit[2] or "").lower()
    assert "préstamos ni tarjetas activos con fecha de pago" not in low
    assert "tarjetas de crédito" in low or "tarjeta" in low

    snap2 = CustomerContextSnapshot(
        customer_id="A1",
        display_name="Ana",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="TC001", product_type="CREDIT_CARD",
                alias="Visa Premium", currency="DOP", status="active",
                card_mask="****C001", credit_limit=Decimal("50000"),
                ledger_balance=Decimal("12000"), available_balance=Decimal("38000"),
                available_purchases_domestic=Decimal("38000"), cutoff_day=15,
            ),
        ),
        loans=(),
    )
    hit2 = run_field_fastpath(snap2, q, None)
    assert hit2 is not None
    text2 = hit2[2] or ""
    low2 = text2.lower()
    assert "12000" in text2.replace(",", "") or "12,000" in text2 or "adeud" in low2
    assert "38000" in text2.replace(",", "") or "38,000" in text2 or "disponible" in low2
    assert "fecha" in low2 or "corte" in low2
    assert hit2[4] == "compound_card"


def test_compound_saldo_minimo_disponible() -> None:
    """Usuario: saldo actual + pago mínimo + límite disponible → los 3, no solo uno."""
    from genesis_cognitive.router.final_response_agent import build_card_detail_response
    from genesis_cognitive.router.field_guardrails import is_compound_personal_query

    q = "Cual es el saldo actual, el pago minimo, el limite disponible?"
    assert is_compound_personal_query(q) is True
    card = ProductSnapshot(
        product_id="TC6374", product_type="CREDIT_CARD",
        alias="Credito Joven Empleado", currency="DOP", status="active",
        card_mask="****6374", credit_limit=Decimal("50000"),
        ledger_balance=Decimal("34529"), available_balance=Decimal("15471"),
        available_purchases_domestic=Decimal("15471"), min_payment_rd=Decimal("0"),
    )
    text = build_card_detail_response(
        q, card, "usuario 1", "Credito Joven Empleado (****6374)",
    )
    low = text.lower()
    assert "34529" in text.replace(",", "") or "34,529" in text
    assert "pago mínimo" in low or "pago minimo" in low
    assert "15,471" in text or "15471" in text.replace(",", "")

    snap = CustomerContextSnapshot(
        customer_id="U1", display_name="usuario 1", default_currency="DOP",
        products=(card,), loans=(),
    )
    hit = run_field_fastpath(snap, q, None)
    assert hit is not None
    reply = hit[2] or ""
    assert "34529" in reply.replace(",", "") or "34,529" in reply
    assert "15,471" in reply or "15471" in reply.replace(",", "")
    assert "mínimo" in reply.lower() or "minimo" in reply.lower()


def test_upcoming_payment_scan_not_dap() -> None:
    """'préstamo o tarjeta con pago próximo' → resumen, nunca ficha de certificado."""
    from genesis_cognitive.router.field_guardrails import (
        is_upcoming_payment_scan_question,
    )

    q = "Tengo algun prestamo o tarjeta con un pago proximo?"
    assert is_upcoming_payment_scan_question(q) is True

    snap = CustomerContextSnapshot(
        customer_id="U1",
        display_name="usuario 1",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="TC6374",
                product_type="CREDIT_CARD",
                alias="Credito Joven Empleado",
                currency="DOP",
                status="active",
                card_mask="****6374",
                cutoff_day=15,
                available_balance=Decimal("40000"),
            ),
            ProductSnapshot(
                product_id="DAP5511",
                product_type="TERM_DEPOSIT",
                alias="Certificado de Deposito",
                currency="DOP",
                status="active",
                available_balance=Decimal("180755.33"),
                interest_rate=Decimal("8.15"),
                interest_amount=Decimal("34663.65"),
                maturity_date="2026-09-19",
                last_four="5511",
            ),
            ProductSnapshot(
                product_id="LOAN0658",
                product_type="LOAN",
                alias="Prestamo Personal",
                currency="DOP",
                status="active",
                last_four="0658",
            ),
        ),
        loans=(
            LoanSnapshot(
                product_id="LOAN0658",
                loan_type="PERSONAL",
                outstanding_principal=Decimal("412282.54"),
                disbursed_amount=Decimal("500000"),
                annual_interest_rate=Decimal("12"),
                next_due_date="2026-10-05",
                installment_amount=Decimal("0"),
                payoff_amount=Decimal("412282.54"),
                overdue_amount=Decimal("0"),
                delinquency_days=0,
                last_four="0658",
            ),
        ),
    )
    hit = run_field_fastpath(snap, q, None)
    assert hit is not None
    text = hit[2] or ""
    low = text.lower()
    assert hit[4] == "upcoming_payments"
    assert "ventana temporal" in low or "america/santo_domingo" in low
    assert "2026-10-05" in text or "pago próximo" in low or "pago proximo" in low
    assert "certificado" not in low
    assert "180755" not in text.replace(",", "")
    assert "5511" not in text
    assert "préstamo" in low or "prestamo" in low or "0658" in text
    assert "tarjeta" in low or "6374" in text or "corte" in low
