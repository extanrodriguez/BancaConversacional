"""Issues APK reportados: corte tras selección, responsabilidad, Visa Joven, fecha límite."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import PendingAction
from genesis_cognitive.rag.kb_intent_resolver import clear_kb_intent_cache, resolve_knowledge_intent
from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail, clear_faq_cache
from genesis_cognitive.router.field_guardrails import (
    apply_card_field_guardrail,
    is_bank_card_catalog_question,
    is_card_field_question,
    run_field_fastpath,
)
from genesis_cognitive.router.final_response_agent import build_card_detail_response


def _snap_cards() -> CustomerContextSnapshot:
    products = (
        ProductSnapshot(
            product_id="TC6374",
            product_type="CREDIT_CARD",
            alias="Credito Joven Empleado",
            currency="DOP",
            status="active",
            card_mask="****6374",
            credit_limit=Decimal("30000"),
            cutoff_day=8,
        ),
        ProductSnapshot(
            product_id="TC7111",
            product_type="CREDIT_CARD",
            alias="Multicredito Empleado",
            currency="DOP",
            status="active",
            card_mask="****7111",
            credit_limit=Decimal("50000"),
            cutoff_day=3,
        ),
        ProductSnapshot(
            product_id="TC3446",
            product_type="CREDIT_CARD",
            alias="Visa Joven",
            currency="DOP",
            status="active",
            card_mask="****3446",
            credit_limit=Decimal("20000"),
            cutoff_day=15,
        ),
    )
    return CustomerContextSnapshot(
        customer_id="APK",
        display_name="usuario 1",
        default_currency="DOP",
        products=products,
        loans=(),
    )


def test_card_selection_keeps_cutoff_field() -> None:
    card = _snap_cards().products[0]
    text = build_card_detail_response(
        "Cual es la fecha de corte de mi tarjeta?",
        card,
        "usuario 1",
        "Credito Joven Empleado (****6374)",
    )
    low = text.lower()
    assert "corte" in low and "8" in text
    assert "límite de crédito" not in low and "limite de credito" not in low
    assert "pago mínimo" not in low and "pago minimo" not in low


def test_option_label_without_field_would_be_rich_but_t2_uses_oq() -> None:
    """Simula T2: pregunta de campo = original; opción APK no debe mandar ficha."""
    card = _snap_cards().products[0]
    field = build_card_detail_response(
        "fecha de corte",
        card,
        "usuario 1",
        "Credito Joven Empleado (****6374)",
    )
    option = build_card_detail_response(
        "Credito Joven Empleado (****6374) | credit_card · DOP",
        card,
        "usuario 1",
        "Credito Joven Empleado (****6374)",
    )
    assert "corte" in field.lower()
    assert "8" in field
    # Sin OQ la opción abre ficha; por eso T2 debe pasar original_question
    assert "límite" in option.lower() or "limite" in option.lower() or "corte" in option.lower()


def test_visa_joven_not_multicredito() -> None:
    snap = _snap_cards()
    assert is_card_field_question("Dame info de la tarjeta de credito visa joven")
    assert not is_bank_card_catalog_question("Dame info de la tarjeta de credito visa joven")
    st, acts, text, _ = apply_card_field_guardrail(
        "VALID_CONTRACT",
        [],
        snap,
        "Dame info de la tarjeta de credito visa joven",
        last_resolved_ref="TC7111",  # foco previo Multicrédito
    )
    assert st == "VALID_CONTRACT"
    assert acts[0]["detected_entities"]["account_ref"] == "TC3446"
    low = (text or "").lower()
    assert "7111" not in (text or "")
    # No dump de ficha ni de la tarjeta incorrecta: pide el campo o habla de Visa Joven
    assert "multicredito" not in low and "multicrédito" not in low
    assert "qué dato" in low or "que dato" in low or "joven" in low


def test_visa_joven_cutoff_field() -> None:
    snap = _snap_cards()
    st, acts, text, _ = apply_card_field_guardrail(
        "VALID_CONTRACT",
        [],
        snap,
        "fecha de corte de la tarjeta visa joven",
        last_resolved_ref="TC7111",
    )
    assert acts[0]["detected_entities"]["account_ref"] == "TC3446"
    assert "15" in (text or "")
    assert "corte" in (text or "").lower()
    assert "7111" not in (text or "")


def test_payment_due_not_sold_as_cutoff_only() -> None:
    card = _snap_cards().products[0]
    text = build_card_detail_response(
        "Cual es la fecha limite de pago?",
        card,
        "usuario 1",
        "Credito Joven Empleado (****6374)",
    )
    low = text.lower()
    assert "fecha límite de pago" in low or "fecha limite de pago" in low or "no tengo la fecha límite" in low or "no tengo la fecha limite" in low
    assert "estado de cuenta" in low
    # No debe afirmar que el día 8 ES la fecha límite de pago
    assert "fecha límite de pago de tu" not in low or "es el día **8**" not in text.lower()


def test_cuando_debo_pagar_explains_cutoff_vs_due() -> None:
    card = _snap_cards().products[0]
    text = build_card_detail_response(
        "Y cuando debo pagar la tarjeta?",
        card,
        "usuario 1",
        "Credito Joven Empleado (****6374)",
    )
    low = text.lower()
    assert "corte" in low or "límite" in low or "limite" in low
    assert "estado de cuenta" in low or "fecha límite" in low or "fecha limite" in low


def test_mi_responsabilidad_not_bank_about_us() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    snap = _snap_cards()
    gr = apply_faq_guardrail(snap, "Cual es mi responsabilidad?", None)
    assert gr is not None
    low = (gr[2] or "").lower()
    assert "obligacion" in low or "responsabilidad" in low or "derecho" in low or "cumplir" in low
    assert "persona física o jurídica" not in low and "persona fisica o juridica" not in low


def test_followup_mia_como_cliente() -> None:
    clear_faq_cache()
    clear_kb_intent_cache()
    session = SimpleNamespace(last_knowledge_topic="Derechos y obligaciones del usuario")
    snap = _snap_cards()
    gr = apply_faq_guardrail(
        snap,
        "Esa es la del banco y la mia como cliente?",
        session,
    )
    assert gr is not None
    low = (gr[2] or "").lower()
    assert "persona física o jurídica" not in low and "persona fisica o juridica" not in low
    assert any(s in low for s in ("oblig", "deber", "responsab", "derecho", "pagar", "contrato"))


def test_pending_stores_original_question() -> None:
    pa = PendingAction(
        intent_id="CREDIT_CARD_DETAIL_READ",
        capability_candidate="CREDIT_CARD_DETAIL",
        selected_route="PERSONAL_READ",
        detected_entities={"account_ref": None},
        missing_requirements=["account_ref"],
        suggested_question="¿Cuál tarjeta?",
        original_question="Cual es la fecha de corte de mi tarjeta?",
    )
    assert "corte" in pa.original_question
