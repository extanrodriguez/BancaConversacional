"""Regresión UX: fecha de pago / fallecidos / reclamación bajo azure_plan."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from genesis_cognitive.brain.azure_plan_turn import (
    _eligible_for_deterministic_fastpath,
    run_azure_plan_path,
)
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import SessionState


@pytest.fixture()
def snap() -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id="726588",
        display_name="Felix Prestamos",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="227615", product_type="LOAN", alias="Préstamo",
                currency="DOP", status="active",
            ),
            ProductSnapshot(
                product_id="TC1", product_type="CREDIT_CARD", alias="Tarjeta Joven",
                currency="DOP", status="active", ledger_balance=Decimal("10"),
            ),
        ),
        loans=(
            LoanSnapshot(
                product_id="227615", loan_type="P",
                installment_amount=Decimal("0"),
                annual_interest_rate=Decimal("12.5"),
                outstanding_principal=Decimal("100"),
                delinquency_days=0,
                next_due_date="2026-10-01",
                payoff_amount=Decimal("100"),
            ),
        ),
    )


@pytest.mark.parametrize(
    "question",
    [
        "Cuál es mi fecha límite de pago?",
        "Cuál es el proceso de clientes fallecidos?",
        "Cómo realizo una reclamación?",
    ],
)
def test_reported_ux_questions_are_fastpath_eligible(question: str) -> None:
    assert _eligible_for_deterministic_fastpath(question) is True


@pytest.mark.asyncio
async def test_fecha_limite_pago_clarifies_via_fastpath_bridge(snap) -> None:
    sess = SessionState(customer_id="726588", snapshot=snap)
    out = await run_azure_plan_path(
        question="Cuál es mi fecha límite de pago?",
        safe_question="Cuál es mi fecha límite de pago?",
        session_state=sess,
        history=[],
        customer_snapshot=snap,
        resolver=None,
        model_input_builder=None,
        context_assembler=None,
        input_validator=None,
        conv_id="c-pay",
        customer_id="726588",
        turn_number=1,
        azure_model="x",
        prompt_version="t",
        request_start=time.perf_counter(),
    )
    assert out["status"] == "CLARIFICATION_REQUIRED"
    assert "interpretación semántica" not in (out.get("client_response") or "").lower()
    src = ((out.get("decision_trace") or [{}])[0].get("output") or {}).get("route_source")
    assert str(src).startswith("field_fastpath:")


@pytest.mark.asyncio
async def test_fallecidos_faq_via_fastpath_bridge(snap) -> None:
    sess = SessionState(customer_id="726588", snapshot=snap)
    out = await run_azure_plan_path(
        question="Cuál es el proceso de clientes fallecidos?",
        safe_question="Cuál es el proceso de clientes fallecidos?",
        session_state=sess,
        history=[],
        customer_snapshot=snap,
        resolver=None,
        model_input_builder=None,
        context_assembler=None,
        input_validator=None,
        conv_id="c-fal",
        customer_id="726588",
        turn_number=1,
        azure_model="x",
        prompt_version="t",
        request_start=time.perf_counter(),
    )
    text = (out.get("client_response") or "").lower()
    assert out["status"] == "VALID_CONTRACT"
    assert "definición" not in text or "fallecido" in text
    assert "fallecido" in text or "de cujus" in text
    assert "no encontré esa definición" not in text


@pytest.mark.asyncio
async def test_reclamacion_via_fastpath_bridge(snap) -> None:
    sess = SessionState(customer_id="726588", snapshot=snap)
    out = await run_azure_plan_path(
        question="Cómo realizo una reclamación?",
        safe_question="Cómo realizo una reclamación?",
        session_state=sess,
        history=[],
        customer_snapshot=snap,
        resolver=None,
        model_input_builder=None,
        context_assembler=None,
        input_validator=None,
        conv_id="c-rec",
        customer_id="726588",
        turn_number=1,
        azure_model="x",
        prompt_version="t",
        request_start=time.perf_counter(),
    )
    text = (out.get("client_response") or "").lower()
    assert out["status"] == "VALID_CONTRACT"
    assert "reclam" in text
    assert "seleccionaste **none**" not in text
    assert "no encontré esa definición" not in text
