"""Pruebas V3: institucional, PIN/OTP, disponible vs actual, titularidad, TurnPlan."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from genesis_cognitive.brain.azure_intent_brain import (
    _is_explicit_knowledge_request,
    _is_institutional_entity_request,
    heuristic_intent,
)
from genesis_cognitive.brain.grounded_executor import execute_grounded
from genesis_cognitive.brain.intent_types import IntentPacket
from genesis_cognitive.brain.security_secrets import is_auth_secret_message, scan_auth_secrets
from genesis_cognitive.brain.turn_plan import (
    intent_packet_to_turn_plan,
    validate_turn_plan,
)
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.router.field_guardrails import (
    apply_card_digits_guardrail,
    apply_digit_followup_guardrail,
    apply_generic_balance_guardrail,
    run_field_fastpath,
)


def _snap_mixed() -> CustomerContextSnapshot:
    """1 cuenta DOP + 2 préstamos (perfil tipo QA 726588 lab)."""
    return CustomerContextSnapshot(
        customer_id="SYN-V3",
        display_name="Cliente Sintetico",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="CA1001DOP",
                product_type="SAVINGS",
                alias="Cuenta de ahorros ...1001",
                currency="DOP",
                status="active",
                available_balance=Decimal("50123.00"),
                ledger_balance=Decimal("52000.00"),
            ),
            ProductSnapshot(
                product_id="LOAN27615",
                product_type="LOAN",
                alias="Préstamo ...7615",
                currency="DOP",
                status="active",
            ),
            ProductSnapshot(
                product_id="LOAN27616",
                product_type="LOAN",
                alias="Préstamo ...7616",
                currency="DOP",
                status="active",
            ),
        ),
        loans=(),
    )


def test_institutional_short_detected() -> None:
    assert _is_institutional_entity_request("mision")
    assert _is_institutional_entity_request("vision")
    assert _is_institutional_entity_request("mision del banco")
    assert _is_explicit_knowledge_request("vision")
    pkt = heuristic_intent("mision")
    assert pkt.family == "knowledge"
    assert pkt.rationale == "critical:institutional_entity"


def test_auth_secret_blocks_product_digits() -> None:
    assert is_auth_secret_message("mi pin es 7615")
    scan = scan_auth_secrets("mi pin es 7615")
    assert scan.should_block_product_digit_match
    # Sufijo de producto explícito sin marco de secreto
    assert not scan_auth_secrets("cuenta terminada en 7615").should_block_product_digit_match


def test_digit_followup_ignores_pin_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = _snap_mixed()
    # Si interpretara 7615 como sufijo de préstamo, fallaría el caso X05
    out = apply_digit_followup_guardrail(snap, "mi PIN es 7615", None, None)
    assert out is None
    card_out = apply_card_digits_guardrail(snap, "el OTP 1001 llego")
    assert card_out is None


def test_disponible_routes_to_account_not_loans() -> None:
    snap = _snap_mixed()
    pkt = heuristic_intent("¿Cuánto tengo disponible?")
    assert pkt.product == "account"
    assert pkt.field == "available"
    result = execute_grounded(pkt, snap, question="¿Cuánto tengo disponible?")
    assert result.intent_id in ("ACCOUNT_BALANCE_READ", "PORTFOLIO_QUERY")
    # No debe pedir desambiguación entre préstamos
    assert "préstamo" not in (result.text or "").lower() or result.status == "VALID_CONTRACT"
    if result.status == "VALID_CONTRACT":
        assert "disponible" in (result.text or "").lower() or "50123" in (result.text or "")


def test_saldo_actual_uses_ledger_not_available() -> None:
    snap = _snap_mixed()
    st, acts, txt, sug = apply_generic_balance_guardrail(
        "VALID_CONTRACT", [], snap, "¿Y cuál es el saldo actual?",
    )
    assert st == "VALID_CONTRACT"
    assert txt is not None
    assert "saldo actual" in txt.lower()
    assert "52000" in txt.replace(",", "")
    assert "50123" not in txt.replace(",", "")


def test_third_party_spouse_is_security() -> None:
    pkt = heuristic_intent("¿cuánto saldo tiene mi esposo?")
    assert pkt.field == "security"
    result = execute_grounded(pkt, _snap_mixed(), question="¿cuánto saldo tiene mi esposo?")
    assert result.intent_id == "SECURITY_GUARDRAIL"
    assert "50123" not in (result.text or "")


def test_turn_plan_adapter_and_validation() -> None:
    pkt = IntentPacket("personal", "account", "available", confidence=0.9, source="heuristic")
    plan = intent_packet_to_turn_plan(pkt)
    assert len(plan.tasks) == 1
    assert plan.tasks[0].domain == "personal"
    assert validate_turn_plan(plan) == []


def test_fastpath_auth_secret_message() -> None:
    snap = _snap_mixed()
    hit = run_field_fastpath(snap, "mi pin es 27615", None)
    assert hit is not None
    st, _acts, txt, _sug, step, _intent, _ref = hit
    assert step == "auth_secret"
    assert st == "VALID_CONTRACT"
    assert "pin" in (txt or "").lower() or "seguridad" in (txt or "").lower()


def test_mision_after_loan_focus_hits_faq() -> None:
    """Tras foco de préstamo, 'mision'/'vision' no caen a clarificación genérica."""
    from genesis_cognitive.context.reactive_store import SessionState
    from genesis_cognitive.router.product_focus import remember_product_focus

    snap = _snap_mixed()
    session = SessionState(customer_id=snap.customer_id, snapshot=snap)
    remember_product_focus(session, "LOAN27615", "LOAN")
    hit = run_field_fastpath(snap, "mision", None, session=session)
    assert hit is not None
    st, acts, txt, _sug, step, intent, _ref = hit
    assert st == "VALID_CONTRACT"
    assert intent == "BUSINESS_KNOWLEDGE_QUERY"
    assert step in ("faq", "faq_rest", "knowledge_followup")
    assert txt and len(txt) > 40
    assert "productos o información general" not in (txt or "").lower()


def test_resolve_option_pool_liquidity_not_loans() -> None:
    """PORTFOLIO_QUERY de disponible no debe ofrecer préstamos (falla QA A2)."""
    from genesis_cognitive.context.app_channel import resolve_option_pool

    snap = _snap_mixed()
    pool = resolve_option_pool(
        snap, intent_id="PORTFOLIO_QUERY", question="¿Cuánto tengo disponible?",
    )
    assert all(p.product_type in ("SAVINGS", "CHECKING", "PAYROLL") for p in pool)
    assert not any(p.product_type == "LOAN" for p in pool)


def test_faq_not_blocked_by_pending_for_mision() -> None:
    from genesis_cognitive.context.reactive_store import PendingAction, SessionState
    from genesis_cognitive.router.faq_guardrail import is_personal_portfolio_faq_blocked

    snap = _snap_mixed()
    session = SessionState(customer_id=snap.customer_id, snapshot=snap)
    session.pending_action = PendingAction(
        intent_id="LOAN_DETAIL_READ",
        capability_candidate="LOAN_DETAIL",
        selected_route="PERSONAL_READ",
        detected_entities={"account_ref": None},
        missing_requirements=["account_ref"],
        suggested_question="¿Sobre cuál préstamo?",
        original_question="¿Cuánto debo?",
    )
    assert is_personal_portfolio_faq_blocked("mision", session=session, snapshot=snap) is False
