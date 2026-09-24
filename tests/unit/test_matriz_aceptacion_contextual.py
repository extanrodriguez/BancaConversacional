"""Matriz de aceptación contextual — integración vía interpret/execute (local)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from genesis_cognitive.brain.azure_plan_turn import (
    _eligible_for_deterministic_fastpath,
    run_azure_plan_path,
)
from genesis_cognitive.brain.plan_executor import execute_turn_plan
from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
from genesis_cognitive.brain.semantic_field_catalog import (
    applicable_fields_for_type,
    card_saldo_convention,
)
from genesis_cognitive.context.core_portfolio_mapper import map_core_portfolio
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import SessionState
from genesis_cognitive.model_input.model_input_builder import (
    _project_one_product,
    project_conversation_memory,
)

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "data" / "lab_portfolios" / "qa_726588_contract_demo.json"


@pytest.fixture()
def lab_snap() -> CustomerContextSnapshot:
    raw = json.loads(LAB.read_text(encoding="utf-8"))
    return map_core_portfolio(raw).snapshot


def test_projection_includes_applicable_fields_and_masked_label(lab_snap) -> None:
    cards = [p for p in lab_snap.products if p.product_type == "CREDIT_CARD"]
    assert cards
    joven = next(p for p in cards if "joven" in (p.alias or "").lower())
    proj = _project_one_product(joven)
    assert "balance" in proj.applicable_fields
    assert "available" in proj.applicable_fields
    assert proj.masked_label
    assert proj.product_ref == joven.product_id
    mem = project_conversation_memory(
        SessionState(customer_id="726588", snapshot=lab_snap),
        context_source="lab_fallback",
        portfolio_completeness="lab_fallback",
    )
    assert mem.projection_version == "contextual-v1"
    assert mem.portfolio_completeness == "lab_fallback"


def test_tarjeta_joven_saldo_resolves_without_asking_which_card(lab_snap) -> None:
    plan = interpret_turn_plan(
        "¿Cuál es el saldo de mi tarjeta joven?", None, snapshot=lab_snap,
    )
    assert plan.tasks
    t = plan.tasks[0]
    assert t.object == "credit_card"
    assert t.entity_ref
    assert "joven" in next(
        p.alias.lower() for p in lab_snap.products if p.product_id == t.entity_ref
    )
    assert t.fields == ["balance"]
    assert card_saldo_convention() == "debt"
    pex = execute_turn_plan(plan, lab_snap, "¿Cuál es el saldo de mi tarjeta joven?")
    low = (pex.text or "").lower()
    assert "cuál tarjeta" not in low and "que tarjeta" not in low
    assert pex.status in ("VALID_CONTRACT", "PARTIAL")


def test_compound_p01_not_stolen_by_payment_fastpath() -> None:
    q = (
        "¿Cuánto debo en mi tarjeta de crédito, cuánto tengo disponible "
        "y cuándo es mi fecha límite de pago?"
    )
    assert _eligible_for_deterministic_fastpath(q) is False
    snap = CustomerContextSnapshot(
        customer_id="X",
        display_name="T",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="TC1", product_type="CREDIT_CARD", alias="Visa",
                currency="DOP", status="active", ledger_balance=Decimal("10"),
                available_balance=Decimal("100"),
            ),
        ),
        loans=(),
    )
    plan = interpret_turn_plan(q, None, snapshot=snap)
    fields = []
    for t in plan.tasks:
        if t.object == "credit_card":
            fields.extend(t.fields or [])
    assert "balance" in fields or "available" in fields
    assert "due_date" in fields or "available" in fields


def test_applicable_fields_loan_includes_rate() -> None:
    assert "rate" in applicable_fields_for_type("LOAN")
    assert "maturity" in applicable_fields_for_type("TERM_DEPOSIT")


@pytest.mark.asyncio
async def test_ax_pay_rec_fal_bridge(lab_snap) -> None:
    import time

    for q, needle in (
        ("Cuál es mi fecha límite de pago?", "fecha"),
        ("Cómo realizo una reclamación?", "reclam"),
        ("Cuál es el proceso de clientes fallecidos?", "fallecid"),
    ):
        sess = SessionState(customer_id="726588", snapshot=lab_snap)
        out = await run_azure_plan_path(
            question=q,
            safe_question=q,
            session_state=sess,
            history=[],
            customer_snapshot=lab_snap,
            resolver=None,
            model_input_builder=None,
            context_assembler=None,
            input_validator=None,
            conv_id="ax",
            customer_id="726588",
            turn_number=1,
            azure_model="x",
            prompt_version="t",
            request_start=time.perf_counter(),
        )
        text = (out.get("client_response") or "").lower()
        assert "interpretación semántica" not in text
        assert "no encontré esa definición" not in text
        assert needle in text or out["status"] == "CLARIFICATION_REQUIRED"
