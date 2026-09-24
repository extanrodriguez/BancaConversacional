"""Contexto conversacional: follow-ups KB, responsabilidad banco, fecha pago préstamo."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import PendingAction
from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail, clear_faq_cache
from genesis_cognitive.router.field_guardrails import (
    apply_payment_date_guardrail,
    run_field_fastpath,
)
from genesis_cognitive.router.final_response_agent import build_loan_detail_response
from genesis_cognitive.router.knowledge_followup import (
    expand_knowledge_question,
    is_bank_responsibility_question,
    should_block_personal_followup,
)


def _snap_felix() -> CustomerContextSnapshot:
    loan_p = ProductSnapshot(
        product_id="PR7615",
        product_type="LOAN",
        alias="Préstamo",
        currency="DOP",
        status="active",
        ledger_balance=Decimal("185000"),
    )
    loan_p2 = ProductSnapshot(
        product_id="PR8842",
        product_type="LOAN",
        alias="Préstamo Hipotecario",
        currency="DOP",
        status="active",
        ledger_balance=Decimal("90000"),
    )
    loan = LoanSnapshot(
        product_id="PR7615",
        loan_type="PERSONAL",
        outstanding_principal=Decimal("185000"),
        disbursed_amount=Decimal("200000"),
        annual_interest_rate=Decimal("12.5"),
        next_due_date="2026-09-01",
        maturity_date="2028-09-01",
        installment_amount=Decimal("5000"),
        payoff_amount=Decimal("185000"),
        overdue_amount=Decimal("0"),
        delinquency_days=0,
    )
    loan2 = LoanSnapshot(
        product_id="PR8842",
        loan_type="MORTGAGE",
        outstanding_principal=Decimal("90000"),
        disbursed_amount=Decimal("100000"),
        annual_interest_rate=Decimal("10"),
        next_due_date="2026-09-15",
        maturity_date="2030-01-01",
        installment_amount=Decimal("3000"),
        payoff_amount=Decimal("90000"),
        overdue_amount=Decimal("0"),
        delinquency_days=0,
    )
    return CustomerContextSnapshot(
        customer_id="FELIX",
        display_name="Felix Prestamos",
        default_currency="DOP",
        products=(loan_p, loan_p2),
        loans=(loan, loan2),
    )


def test_como_se_usa_after_ahorros() -> None:
    clear_faq_cache()
    sess = SimpleNamespace(last_knowledge_topic="Cuenta de ahorro", last_resolved=None, product_focus=None)
    snap = _snap_felix()
    hit = run_field_fastpath(snap, "como se usa", None, session=sess)
    assert hit is not None
    st, acts, text, _sug, step, intent, _ref = hit
    assert step == "knowledge_followup"
    assert intent == "BUSINESS_KNOWLEDGE_QUERY"
    low = (text or "").lower()
    assert "hola" not in low or "ahorro" in low
    assert any(s in low for s in ("ahorro", "cajeros", "transfer", "débito", "debito", "fondos"))
    assert "¡hola" not in low


def test_y_la_del_banco_not_loan() -> None:
    clear_faq_cache()
    sess = SimpleNamespace(
        last_knowledge_topic="Derechos y obligaciones del usuario / mi responsabilidad",
        last_resolved=SimpleNamespace(intent_id="LOAN_DETAIL_READ", account_ref="PR7615", original_question="tasa"),
        product_focus=SimpleNamespace(kind="LOAN", product_id="PR7615", intent_id="LOAN_DETAIL_READ", original_question="tasa"),
    )
    assert should_block_personal_followup("y la del banco", sess)
    snap = _snap_felix()
    hit = run_field_fastpath(snap, "y la del banco", sess.last_resolved, session=sess)
    assert hit is not None
    text = hit[2] or ""
    low = text.lower()
    assert "185" not in text.replace(",", "")
    assert "capital pendiente" not in low
    assert any(s in low for s in ("institución", "institucion", "banco", "derechos", "protección", "proteccion"))


def test_responsabilidad_del_banco() -> None:
    clear_faq_cache()
    assert is_bank_responsibility_question("cual es la responsabilidad del banco")
    gr = apply_faq_guardrail(None, "cual es la responsabilidad del banco", None)
    assert gr is not None
    low = (gr[2] or "").lower()
    assert low.startswith("como **institución") or "como institución" in low or "como **institucion" in low or "como institucion" in low
    assert "proporcionar información veraz" not in low


def test_loan_payment_date_keeps_field_after_selection() -> None:
    snap = _snap_felix()
    out = apply_payment_date_guardrail(snap, "cuando debo pagar mis prestamos", None)
    assert out is not None
    st, acts, text, opts = out
    assert st == "CLARIFICATION_REQUIRED" or "fecha" in (text or "").lower() or "préstamo" in (text or "").lower() or "prestamo" in (text or "").lower()
    if acts:
        assert acts[0]["intent_id"] == "PAYMENT_DATE_READ"
    loan = snap.loans[0]
    field = build_loan_detail_response(
        "cuando debo pagar mis prestamos",
        loan.to_detail_dict(),
        "Felix Prestamos",
    )
    option = build_loan_detail_response(
        "Préstamo - 7615 | loan · DOP",
        loan.to_detail_dict(),
        "Felix Prestamos",
    )
    assert "2026-09-01" in field
    assert "próxima fecha de pago" in field.lower() or "proxima fecha de pago" in field.lower()
    # Sin OQ, el label abre ficha; T2 debe usar original_question
    assert "monto original" in option.lower() or "capital" in option.lower()


def test_expand_como_se_usa() -> None:
    sess = SimpleNamespace(last_knowledge_topic="Cuenta de ahorro")
    exp = expand_knowledge_question("como se usa", sess)
    assert "ahorro" in exp.lower()
