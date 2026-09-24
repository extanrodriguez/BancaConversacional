"""Errores controlados, CTA sin producto, y 'sí' tras depósito a plazo."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot, ProductSnapshot
from genesis_cognitive.context.reactive_store import PendingAction
from genesis_cognitive.rag.foundry_kb_agent import build_knowledge_ambiguity_clarification
from genesis_cognitive.router.field_guardrails import (
    apply_affirmation_guardrail,
    apply_card_field_guardrail,
    apply_dap_field_guardrail,
    run_field_fastpath,
)


def _snap_no_dap() -> CustomerContextSnapshot:
    sav = ProductSnapshot(
        product_id="CA08001",
        product_type="SAVINGS",
        alias="Cuenta de ahorros",
        currency="DOP",
        status="active",
        available_balance=Decimal("50000"),
    )
    return CustomerContextSnapshot(
        customer_id="FELIX",
        display_name="Felix Prestamos",
        default_currency="DOP",
        products=(sav,),
        loans=(),
    )


def test_mi_deposito_no_es_ambiguedad_kb() -> None:
    assert build_knowledge_ambiguity_clarification("y mi deposito a plazo", "Felix Prestamos") is None


def test_mi_deposito_sin_producto_trae_enlace() -> None:
    snap = _snap_no_dap()
    session = SimpleNamespace(
        last_resolved=SimpleNamespace(
            intent_id="ACCOUNT_BALANCE_READ",
            account_ref="CA08001",
            original_question="puedes darme el saldo de mi cuenta",
        ),
        product_focus=SimpleNamespace(original_question="puedes darme el saldo de mi cuenta"),
        last_knowledge_topic=None,
        pending_action=None,
    )
    st, _acts, text, _sug = apply_dap_field_guardrail(
        "VALID_CONTRACT", [], snap, "y mi deposito a plazo", session=session,
    )
    assert st == "VALID_CONTRACT"
    low = (text or "").lower()
    assert "no tienes" in low
    assert "solicitudesdigitales.bsc.com.do" in low
    assert "50000" not in (text or "")


def test_si_tras_aclaracion_dap_no_reusa_ahorro() -> None:
    snap = _snap_no_dap()
    session = SimpleNamespace(
        last_resolved=SimpleNamespace(
            intent_id="ACCOUNT_BALANCE_READ",
            account_ref="CA08001",
            original_question="saldo de mi cuenta",
        ),
        product_focus=None,
        last_knowledge_topic="KB_AMBIGUITY",
        pending_action=PendingAction(
            intent_id="BUSINESS_KNOWLEDGE_QUERY",
            capability_candidate="BUSINESS_KNOWLEDGE",
            selected_route="BUSINESS_RAG",
            detected_entities={"account_ref": None, "knowledge_topic": "KB_AMBIGUITY"},
            missing_requirements=["knowledge_topic"],
            suggested_question="¿te refieres a la definición del depósito a plazo?",
        ),
    )
    hit = run_field_fastpath(snap, "si", session.last_resolved, session=session)
    assert hit is not None
    text = hit[2] or ""
    assert "50000" not in text
    assert "solicitudesdigitales.bsc.com.do" in text.lower() or "depósito" in text.lower() or "deposito" in text.lower()


def test_sin_tarjetas_incluye_enlace() -> None:
    snap = _snap_no_dap()
    st, _acts, text, _ = apply_card_field_guardrail(
        "VALID_CONTRACT", [], snap, "dame info de mis tarjetas de credito",
    )
    assert st == "VALID_CONTRACT"
    assert "no tienes" in (text or "").lower()
    assert "solicitudesdigitales.bsc.com.do" in (text or "").lower()
