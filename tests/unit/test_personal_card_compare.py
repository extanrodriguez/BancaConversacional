"""Comparación personal de tarjetas (regresión 8447 vs 8446)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from genesis_cognitive.brain.azure_plan_adapter import is_unequivocal_structured_shortcut
from genesis_cognitive.brain.plan_executor import execute_turn_plan
from genesis_cognitive.brain.plan_interpreter import (
    _match_cards_mentioned_in_question,
    interpret_turn_plan,
)
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import SessionState


def _snap() -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id="726588",
        display_name="Cliente",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="CA1",
                product_type="SAVINGS",
                alias="Cuenta de ahorros",
                currency="DOP",
                status="active",
                available_balance=Decimal("1000"),
            ),
            ProductSnapshot(
                product_id="CC1",
                product_type="CHECKING",
                alias="Cuenta corriente",
                currency="DOP",
                status="active",
                available_balance=Decimal("500"),
            ),
            ProductSnapshot(
                product_id="TC_JOVEN",
                product_type="CREDIT_CARD",
                alias="Tarjeta Joven",
                currency="DOP",
                status="active",
                ledger_balance=Decimal("2398.43"),
                available_balance=Decimal("100000"),
                available_purchases_domestic=Decimal("100000"),
            ),
            ProductSnapshot(
                product_id="TC_FULL",
                product_type="CREDIT_CARD",
                alias="Visa Full Car Flotilla Empleado",
                currency="DOP",
                status="active",
                ledger_balance=Decimal("0"),
                available_balance=Decimal("5000"),
                available_purchases_domestic=Decimal("5000"),
            ),
        ),
        loans=(),
    )


Q = "comparame mi tarjeta Tarjetas de crédito Visa Full Car con la tarjeta joven"


def test_match_both_named_cards() -> None:
    hits = _match_cards_mentioned_in_question(Q, _snap())
    ids = {p.product_id for p in hits}
    assert "TC_JOVEN" in ids
    assert "TC_FULL" in ids


def test_personal_compare_not_kb_shortcut() -> None:
    ok, reason = is_unequivocal_structured_shortcut(Q, session=None)
    # No debe forzar kb_catalog_compare
    assert not (ok and reason == "kb_catalog_compare")


def test_plan_and_execute_card_compare() -> None:
    snap = _snap()
    sess = SessionState(customer_id="726588", snapshot=snap)
    plan = interpret_turn_plan(Q, session=sess, snapshot=snap)
    assert any(
        t.domain == "personal"
        and t.object == "credit_card"
        and t.cardinality == "all"
        for t in plan.tasks
    )
    assert not any(t.domain == "catalog" and t.action == "compare" for t in plan.tasks)
    pex = execute_turn_plan(plan, snapshot=snap, question=Q, session=sess)
    assert pex.status == "VALID_CONTRACT"
    text = (pex.text or "").lower()
    assert "joven" in text
    assert "full car" in text or "full" in text
    assert "cuenta de ahorros" not in text
    assert "cuenta corriente" not in text
