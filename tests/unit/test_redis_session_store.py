"""Unit tests for RedisSessionStore serializers (no live Redis required)."""

from __future__ import annotations

from decimal import Decimal

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import LastResolved, PendingAction, SessionState
from genesis_cognitive.context.redis_session_store import (
    session_from_dict,
    session_to_dict,
    snapshot_from_dict,
    snapshot_to_dict,
)


def test_snapshot_roundtrip() -> None:
    snap = CustomerContextSnapshot(
        customer_id="X",
        display_name="Ana",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="1",
                product_type="SAVINGS",
                alias="Ahorros",
                currency="DOP",
                status="active",
                available_balance=Decimal("10.50"),
            ),
        ),
        loans=(),
    )
    restored = snapshot_from_dict(snapshot_to_dict(snap))
    assert restored.customer_id == "X"
    assert restored.products[0].available_balance == Decimal("10.50")


def test_session_roundtrip() -> None:
    session = SessionState(
        customer_id="X",
        history=[{"role": "user", "content": "hola"}],
        last_resolved=LastResolved(
            intent_id="ACCOUNT_BALANCE_READ",
            account_ref="1",
            original_question="saldo",
        ),
    )
    restored = session_from_dict(session_to_dict(session))
    assert restored.customer_id == "X"
    assert restored.last_resolved is not None
    assert restored.last_resolved.account_ref == "1"


def test_pending_query_spec_roundtrip() -> None:
    session = SessionState(
        customer_id="X",
        pending_action=PendingAction(
            intent_id="TERM_DEPOSIT_DETAIL_READ",
            capability_candidate="TERM_DEPOSIT_DETAIL",
            selected_route="PERSONAL_READ",
            detected_entities={"account_ref": None},
            missing_requirements=["account_ref"],
            suggested_question="¿Cuál certificado?",
            original_question="dame la tasa de mis certificados",
            query_spec={
                "field": "rate",
                "scope": "single",
                "response_shape": "field",
                "intent_id": "TERM_DEPOSIT_DETAIL_READ",
            },
        ),
    )
    restored = session_from_dict(session_to_dict(session))
    assert restored.pending_action is not None
    assert restored.pending_action.original_question == "dame la tasa de mis certificados"
    assert restored.pending_action.query_spec["field"] == "rate"
