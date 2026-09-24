"""Escenarios reales funcionales: intención KB, DAP, fecha corte/pago, ambigüedad."""

from __future__ import annotations

from decimal import Decimal

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.rag.kb_intent_resolver import clear_kb_intent_cache, resolve_knowledge_intent
from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail, clear_faq_cache
from genesis_cognitive.router.field_guardrails import (
    apply_dap_field_guardrail,
    is_ambiguous_product_noun_question,
    is_bank_card_catalog_question,
    run_field_fastpath,
)
from genesis_cognitive.router.final_response_agent import (
    build_card_detail_response,
    build_loan_detail_response,
)


def _snap() -> CustomerContextSnapshot:
    products = (
        ProductSnapshot(
            product_id="11042010152113",
            product_type="SAVINGS",
            alias="Cuenta de Ahorros",
            currency="DOP",
            status="active",
            available_balance=Decimal("5446.01"),
        ),
        ProductSnapshot(
            product_id="220710021030101222",
            product_type="CREDIT_CARD",
            alias="Visa Full Car Flotilla Empleado",
            currency="DOP",
            status="active",
            card_mask="****1222",
            cutoff_day=8,
            credit_limit=Decimal("50000"),
        ),
        ProductSnapshot(
            product_id="33012010005511",
            product_type="TERM_DEPOSIT",
            alias="Certificado de Depósito",
            currency="DOP",
            status="active",
            available_balance=Decimal("100000"),
            ledger_balance=Decimal("105000"),
            interest_rate=Decimal("7.5"),
        ),
        ProductSnapshot(
            product_id="33012010005809",
            product_type="TERM_DEPOSIT",
            alias="Certificado de Depósito",
            currency="DOP",
            status="active",
            available_balance=Decimal("200000"),
        ),
        ProductSnapshot(
            product_id="33012010006935",
            product_type="TERM_DEPOSIT",
            alias="Certificado de Depósito",
            currency="DOP",
            status="active",
            available_balance=Decimal("300000"),
        ),
        ProductSnapshot(
            product_id="PR10658",
            product_type="LOAN",
            alias="Préstamo personal",
            currency="DOP",
            status="active",
        ),
    )
    loans = (
        LoanSnapshot(
            product_id="PR10658",
            loan_type="Personal",
            installment_amount=Decimal("0"),
            annual_interest_rate=Decimal("10"),
            outstanding_principal=Decimal("412282.54"),
            delinquency_days=0,
            next_due_date="2026-08-25",
            disbursed_amount=Decimal("600000"),
            payoff_amount=Decimal("424765.54"),
            maturity_date="2026-08-25",
            last_four="0658",
        ),
    )
    return CustomerContextSnapshot(
        customer_id="U1",
        display_name="usuario 1",
        default_currency="DOP",
        products=products,
        loans=loans,
    )


def test_cutoff_day_completa_frase() -> None:
    card = _snap().products[1]
    text = build_card_detail_response(
        "CUAL ES LA FECHA DE CORTE DE MI TARJETA?",
        card,
        "usuario 1",
        "Visa Full Car Flotilla Empleado (****1222)",
    )
    assert "8" in text
    assert "de cada mes" in text.lower()


def test_proceso_contratar_no_reclamacion() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    gr = apply_faq_guardrail(_snap(), "CUAL ES EL PROCESO PARA CONTRATAR UN PRODUCTO?", None)
    assert gr is not None
    low = (gr[2] or "").lower()
    assert "reclam" not in low
    assert "solicitudesdigitales" in low or "contratar" in low


def test_tarjetas_ofrece_banco_catalog() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    assert is_bank_card_catalog_question("¿CUALES TARJETAS OFRECE EL BANCO?")
    hit = run_field_fastpath(_snap(), "¿CUALES TARJETAS OFRECE EL BANCO?", None)
    assert hit is not None
    low = (hit[2] or "").lower()
    assert "visa" in low or "débito" in low or "debito" in low
    assert "emprendedores" not in low
    assert "misión" not in low and "mision" not in low or "tarjeta" in low


def test_tarjetas_debito_banco() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    hit = run_field_fastpath(_snap(), "CUALES TARJETAS DE DEBITO TIENE EL BANCO?", None)
    assert hit is not None
    low = (hit[2] or "").lower()
    assert "débito" in low or "debito" in low
    assert "visión" not in low and "vision es ser" not in low


def test_dap_apk_selection_5511() -> None:
    snap = _snap()
    msg = "Depósito a plazo …5511\nDEPOSITO_PLAZO_5511"
    st, acts, text, _ = apply_dap_field_guardrail("VALID_CONTRACT", [], snap, msg)
    assert st == "VALID_CONTRACT"
    assert acts[0]["detected_entities"]["account_ref"].endswith("5511")
    assert "5809" not in (text or "")
    assert "6935" not in (text or "")
    # ficha, no solo balance genérico
    assert "capital" in (text or "").lower() or "tasa" in (text or "").lower() or "5511" in (text or "")


def test_cuenta_corriente_definition() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    gr = apply_faq_guardrail(_snap(), "QUE ES UNA CUENTA CORRIENTE?", None)
    assert gr is not None
    low = (gr[2] or "").lower()
    assert "corriente" in low
    assert "medio de pago" not in low  # no definición de débito


def test_que_es_certificado_no_condiciones_prestamo() -> None:
    """'qué es un certificado de depósito' ≠ condiciones financieras de préstamos."""
    clear_faq_cache()
    clear_kb_intent_cache()
    q = "que es un certificado de deposito"
    hit = run_field_fastpath(_snap(), q, None)
    assert hit is not None
    text = hit[2] or ""
    low = text.lower()
    assert "depósito" in low or "deposito" in low or "certificado" in low or "plazo" in low
    assert "créditos de consumo" not in low and "creditos de consumo" not in low
    assert "condiciones financieras" not in low
    assert "hipotecarios para la vivienda" not in low
    # También vía KB intent directo
    kb = resolve_knowledge_intent(q, min_score=0.3)
    assert kb is not None
    kb_low = (kb.get("answer") or "").lower()
    assert "condiciones financieras" not in kb_low
    assert "créditos de consumo" not in kb_low and "creditos de consumo" not in kb_low
    assert "depósito" in kb_low or "deposito" in kb_low or "plazo" in kb_low or "inversión" in kb_low or "inversion" in kb_low


def test_cuentas_corrientes_ambiguous() -> None:
    assert is_ambiguous_product_noun_question("CUENTAS CORRIENTES")
    hit = run_field_fastpath(_snap(), "CUENTAS CORRIENTES", None)
    assert hit is not None
    assert hit[0] == "CLARIFICATION_REQUIRED"
    low = (hit[2] or "").lower()
    assert "qué es" in low or "que es" in low or "definición" in low or "portafolio" in low or "tienes" in low
    assert "5446" not in (hit[2] or "")


def test_como_contrato_credito_diferido() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    gr = apply_faq_guardrail(None, "COMO CONTRATO UN CREDITO DIFERIDO?", None)
    assert gr is not None
    low = (gr[2] or "").lower()
    assert "solicitar" in low or "centro de negocios" in low or "document" in low or "solicitudesdigitales" in low
    assert not low.strip().startswith("crédito diferido: producto integral")


def test_condiciones_multicredito_not_debit() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    hit = resolve_knowledge_intent("CUALES SON LAS CONDICIONES DE USO DEL MULTICREDITO?", min_score=0.3)
    assert hit is not None
    low = ((hit.get("topic") or "") + " " + (hit.get("product") or "") + " " + (hit.get("answer") or "")).lower()
    assert "multicredit" in low or "diferido" in low or "cuotas" in low
    assert "contactless" not in (hit.get("answer") or "").lower()


def test_cargos_multicredito_not_glossary() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    gr = apply_faq_guardrail(None, "¿CUÁLES SON LOS CARGOS DEL MULTICRÉDITO?", None)
    assert gr is not None
    low = (gr[2] or "").lower()
    assert "multicredit" in low or "emisión" in low or "emision" in low or "renovación" in low
    assert not low.startswith("cargo: es el monto aplicado")


def test_responsabilidad_not_about_us() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    gr = apply_faq_guardrail(None, "CUAL ES MI RESPONSABILIDAD EN EL BANCO?", None)
    assert gr is not None
    low = (gr[2] or "").lower()
    assert "derecho" in low or "oblig" in low or "responsab" in low
    assert "emprendedores" not in low


def test_loan_payment_date_only() -> None:
    loan = _snap().loans[0].to_detail_dict()
    text = build_loan_detail_response(
        "Y LA FECHA DE PAGO DE MI PRESTAMO TERMINADO EN 0658",
        loan,
        "usuario 1",
    )
    low = text.lower()
    assert "2026-08-25" in text
    assert "monto original" not in low
    assert "capital pendiente" not in low
    assert "tasa anual" not in low
