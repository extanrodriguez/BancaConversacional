"""Fixes Fase 1: DAP selección, catálogo tarjetas, nombres TC, fecha de pago ambigua."""

from __future__ import annotations

from decimal import Decimal

from genesis_cognitive.context.app_channel import build_product_option
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.response_formatting import (
    DIGITAL_ONBOARDING_URL,
    append_digital_onboarding_link,
    build_rich_card_detail,
)
from genesis_cognitive.router.deposit_guardrail import _find_text_candidates
from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail, clear_faq_cache
from genesis_cognitive.router.field_guardrails import (
    apply_dap_field_guardrail,
    apply_payment_date_guardrail,
    is_bank_card_catalog_question,
    is_personal_payment_date_question,
    run_field_fastpath,
)


def _snap_mixed() -> CustomerContextSnapshot:
    products = (
        ProductSnapshot(
            product_id="33012010005511",
            product_type="TERM_DEPOSIT",
            alias="Certificado de Depósito",
            currency="DOP",
            status="active",
            available_balance=Decimal("500000"),
        ),
        ProductSnapshot(
            product_id="33012010008842",
            product_type="TERM_DEPOSIT",
            alias="Certificado de Depósito",
            currency="USD",
            status="active",
            available_balance=Decimal("10000"),
        ),
        ProductSnapshot(
            product_id="250925031840000011",
            product_type="CREDIT_CARD",
            alias="Visa Joven",
            currency="DOP",
            status="active",
            card_mask="****3446",
            credit_limit=Decimal("50000"),
            cutoff_day=15,
        ),
        ProductSnapshot(
            product_id="220710021030100868",
            product_type="CREDIT_CARD",
            alias="Visa Multicrédito",
            currency="DOP",
            status="active",
            card_mask="****6582",
            credit_limit=Decimal("100000"),
            cutoff_day=8,
        ),
        ProductSnapshot(
            product_id="PR27615",
            product_type="LOAN",
            alias="Préstamo personal",
            currency="DOP",
            status="active",
            ledger_balance=Decimal("80000"),
        ),
    )
    loans = (
        LoanSnapshot(
            product_id="PR27615",
            loan_type="Personal",
            installment_amount=Decimal("0"),
            annual_interest_rate=Decimal("12"),
            outstanding_principal=Decimal("80000"),
            delinquency_days=0,
            next_due_date="2026-09-20",
        ),
    )
    return CustomerContextSnapshot(
        customer_id="TEST-FIX",
        display_name="Felix",
        default_currency="DOP",
        products=products,
        loans=loans,
    )


def test_dap_select_by_option_ref() -> None:
    snap = _snap_mixed()
    st, acts, text, _sug = apply_dap_field_guardrail(
        "VALID_CONTRACT", [], snap, "DEPOSITO_PLAZO_5511",
    )
    assert st == "VALID_CONTRACT"
    assert acts[0]["detected_entities"]["account_ref"] == "33012010005511"
    assert "5511" in (text or "") or "500" in (text or "").replace(",", "")
    assert "8842" not in (text or "")


def test_dap_select_by_digits_after_list() -> None:
    snap = _snap_mixed()
    st, acts, text, _ = apply_dap_field_guardrail(
        "VALID_CONTRACT", [], snap, "Certificado de Depósito - 5511",
    )
    assert st == "VALID_CONTRACT"
    assert acts[0]["detected_entities"]["account_ref"].endswith("5511")


def test_dap_list_asks_selection() -> None:
    snap = _snap_mixed()
    hit = run_field_fastpath(snap, "dame mis certificados", None)
    assert hit is not None
    st, acts, text, sug, step, intent, _ref = hit
    assert step == "portfolio"
    assert st == "CLARIFICATION_REQUIRED"
    assert intent == "TERM_DEPOSIT_DETAIL_READ"
    assert sug and len(sug) >= 2
    assert "5511" in (text or "") or "cual" in (text or "").lower() or "cuál" in (text or "").lower()


def test_bank_card_catalog_not_general_products() -> None:
    clear_faq_cache()
    assert is_bank_card_catalog_question("qué productos de tarjeta tiene el banco")
    gr = apply_faq_guardrail(None, "qué productos de tarjeta tiene el banco", None)
    assert gr is not None
    text = gr[2] or ""
    low = text.lower()
    assert "visa" in low or "multicrédito" in low or "multicredito" in low or "débito" in low or "debito" in low
    assert "hipotecario" not in low  # no catálogo general de préstamos
    assert "](" in text and "solicitudesdigitales" in text


def test_digital_link_is_markdown() -> None:
    out = append_digital_onboarding_link("Detalle de producto.")
    assert f"]({DIGITAL_ONBOARDING_URL})" in out or f"]({DIGITAL_ONBOARDING_URL.rstrip('/')})" in out
    # Normaliza URL cruda a markdown
    raw = append_digital_onboarding_link(
        f"Info.\n\nPara contratar de forma digital, ingresa a: {DIGITAL_ONBOARDING_URL}"
    )
    assert "](" in raw


def test_card_label_uses_product_name() -> None:
    card = ProductSnapshot(
        product_id="250925031840000011",
        product_type="CREDIT_CARD",
        alias="Visa Joven",
        currency="DOP",
        status="active",
        card_mask="****3446",
    )
    rich = build_rich_card_detail(card)
    assert "Visa Joven" in rich
    opt = build_product_option(card, [card])
    assert "Visa Joven" in opt["label"]


def test_card_match_by_product_name() -> None:
    snap = _snap_mixed()
    cards = [p for p in snap.products if p.product_type == "CREDIT_CARD"]
    hits = _find_text_candidates("quiero info de mi visa joven", cards)
    assert len(hits) == 1
    assert "Joven" in (hits[0].alias or "")


def test_payment_date_ambiguous_asks_product() -> None:
    snap = _snap_mixed()
    assert is_personal_payment_date_question("cuál es la fecha de pago")
    out = apply_payment_date_guardrail(snap, "cuál es la fecha de pago")
    assert out is not None
    st, _acts, text, sug = out
    assert st == "CLARIFICATION_REQUIRED"
    low = (text or "").lower()
    assert "préstamo" in low or "prestamo" in low or "tarjeta" in low or "visa" in low
    assert "último día" not in low and "tarjetahabiente" not in low
    assert sug is None or len(sug) >= 2

    hit = run_field_fastpath(snap, "cuál es la fecha de pago", None)
    assert hit is not None
    assert hit[4] == "payment_date"
    assert hit[0] == "CLARIFICATION_REQUIRED"


def test_card_name_not_bank_faq() -> None:
    clear_faq_cache()
    snap = _snap_mixed()
    # Sustituir alias por uno con "Santa Cruz" (caso real QA)
    products = list(snap.products)
    products[2] = ProductSnapshot(
        product_id="250925031840000011",
        product_type="CREDIT_CARD",
        alias="Visa Bravo Santa Cruz",
        currency="DOP",
        status="active",
        card_mask="****3446",
        credit_limit=Decimal("50000"),
        cutoff_day=15,
    )
    snap = CustomerContextSnapshot(
        customer_id=snap.customer_id,
        display_name=snap.display_name,
        default_currency=snap.default_currency,
        products=tuple(products),
        loans=snap.loans,
    )
    hit = run_field_fastpath(snap, "Visa Bravo Santa Cruz", None)
    assert hit is not None
    st, acts, text, _sug, step, intent, ref = hit
    assert step == "card", f"esperado card, got {step}: {text}"
    assert intent == "CREDIT_CARD_DETAIL_READ"
    assert ref and ref.endswith("00011")
    assert "institución financiera" not in (text or "").lower()
    assert "Bravo" in (text or "") or "3446" in (text or "")
    clear_faq_cache()
    assert not is_personal_payment_date_question("qué es fecha límite de pago")
    gr = apply_faq_guardrail(None, "qué es Fecha límite de pago", None)
    assert gr is not None
    assert "tarjetahabiente" in (gr[2] or "").lower() or "último día" in (gr[2] or "").lower() or "ultimo dia" in (gr[2] or "").lower()


def _snap_dap_followup() -> CustomerContextSnapshot:
    """Snapshot del escenario video: 3 DAP + cuenta ahorro."""
    products = (
        ProductSnapshot(
            product_id="33012010005511",
            product_type="TERM_DEPOSIT",
            alias="Certificado de Depósito",
            currency="DOP",
            status="active",
            available_balance=Decimal("500000"),
            interest_rate=Decimal("8.5"),
            maturity_date="2027-01-15",
        ),
        ProductSnapshot(
            product_id="33012010005809",
            product_type="TERM_DEPOSIT",
            alias="Certificado de Depósito",
            currency="DOP",
            status="active",
            available_balance=Decimal("250000"),
            interest_rate=Decimal("9.0"),
            maturity_date="2026-12-01",
        ),
        ProductSnapshot(
            product_id="33012010008842",
            product_type="TERM_DEPOSIT",
            alias="Certificado de Depósito",
            currency="USD",
            status="active",
            available_balance=Decimal("10000"),
            interest_rate=Decimal("3.5"),
            maturity_date="2027-06-01",
        ),
        ProductSnapshot(
            product_id="10112113",
            product_type="SAVINGS",
            alias="Cuenta de ahorros",
            currency="DOP",
            status="active",
            available_balance=Decimal("15000"),
        ),
    )
    return CustomerContextSnapshot(
        customer_id="TEST-VIDEO",
        display_name="Felix",
        default_currency="DOP",
        products=products,
        loans=(),
    )


def test_digit_followup_keeps_dap_and_tasa() -> None:
    """Video: tras tasa de un DAP, 'Y del 05809?' no debe dar saldo de ahorro."""
    from types import SimpleNamespace

    from genesis_cognitive.context.reactive_store import LastResolved, ProductFocus
    from genesis_cognitive.router.product_focus import should_update_last_resolved

    snap = _snap_dap_followup()
    session = SimpleNamespace(
        last_resolved=LastResolved(
            intent_id="TERM_DEPOSIT_DETAIL_READ",
            account_ref="33012010005511",
            original_question="cuál es la tasa de mi certificado 5511",
        ),
        product_focus=ProductFocus(
            kind="TERM_DEPOSIT",
            product_id="33012010005511",
            intent_id="TERM_DEPOSIT_DETAIL_READ",
            original_question="cuál es la tasa de mi certificado 5511",
        ),
    )
    hit = run_field_fastpath(snap, "Y del 05809?", session.last_resolved, session=session)
    assert hit is not None
    st, acts, text, _sug, step, intent, ref = hit
    assert step == "digit_followup"
    assert st == "VALID_CONTRACT"
    assert intent == "TERM_DEPOSIT_DETAIL_READ"
    assert ref and ref.endswith("5809")
    low = (text or "").lower()
    assert "tasa" in low or "9" in (text or "")
    assert "ahorro" not in low
    assert "12113" not in (text or "")
    # Un saldo mal resuelto no debe pisar el foco DAP
    assert not should_update_last_resolved(
        "ACCOUNT_BALANCE_READ", "10112113", session, "Y del 05809?",
    )


def test_dap_correction_resumes_focused_field() -> None:
    """Video: 'Del deposito a plazo fue que te pregunte' reanuda DAP+campo, no lista."""
    from types import SimpleNamespace

    from genesis_cognitive.context.reactive_store import LastResolved, ProductFocus

    snap = _snap_dap_followup()
    session = SimpleNamespace(
        # last_resolved pisado por saldo erróneo (como en el video)
        last_resolved=LastResolved(
            intent_id="ACCOUNT_BALANCE_READ",
            account_ref="10112113",
            original_question="Y del 05809?",
        ),
        product_focus=ProductFocus(
            kind="TERM_DEPOSIT",
            product_id="33012010005809",
            intent_id="TERM_DEPOSIT_DETAIL_READ",
            original_question="cuál es la tasa de mi certificado",
        ),
    )
    hit = run_field_fastpath(
        snap,
        "Del deposito a plazo fue que te pregunte",
        session.last_resolved,
        session=session,
    )
    assert hit is not None
    st, acts, text, _sug, step, intent, ref = hit
    assert step in ("dap_correction", "dap")
    assert st == "VALID_CONTRACT"
    assert intent == "TERM_DEPOSIT_DETAIL_READ"
    assert ref and ref.endswith("5809")
    low = (text or "").lower()
    assert "tasa" in low or "9" in (text or "")
    # No debe volver a pedir selección de los 3 DAP
    assert "cuál de" not in low and "cual de" not in low
