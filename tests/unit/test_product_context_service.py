"""ProductContextService — READ PATH trusted session isolation."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.product_context_service import (
    GetCustomerProductsQuery,
    ProductContextService,
    ProductContextToolType,
    TrustedSessionIdentity,
)
from genesis_cognitive.context.reactive_store import ReactiveSessionStore


def _sample_snapshot(customer_id: str) -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id=customer_id,
        display_name="Cliente A",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="CA001",
                product_type="SAVINGS",
                alias="Ahorro",
                currency="DOP",
                status="active",
                available_balance=Decimal("1000"),
                ledger_balance=Decimal("1000"),
            ),
            ProductSnapshot(
                product_id="TC001",
                product_type="CREDIT_CARD",
                alias="Visa",
                currency="DOP",
                status="active",
                ledger_balance=Decimal("5000"),
            ),
        ),
        loans=(
            LoanSnapshot(
                product_id="PR001",
                loan_type="personal",
                installment_amount=Decimal("0"),
                annual_interest_rate=Decimal("12.5"),
                outstanding_principal=Decimal("325000"),
                delinquency_days=0,
                next_due_date="2026-10-01",
            ),
        ),
    )


@pytest.fixture
def store() -> ReactiveSessionStore:
    return ReactiveSessionStore(session_ttl_s=3600.0)


def test_session_isolation_forbidden_customer_hint(store: ReactiveSessionStore) -> None:
    sess = store.create_session("conv-a", "111")
    sess.snapshot = _sample_snapshot("111")
    store.put_session("conv-a", sess)

    svc = ProductContextService(store)
    identity = svc.resolve_trusted_identity("conv-a", customer_id_hint="999")
    assert identity is None


def test_get_customer_products_loan_filter(store: ReactiveSessionStore) -> None:
    sess = store.create_session("conv-b", "726588")
    sess.snapshot = _sample_snapshot("726588")
    store.put_session("conv-b", sess)

    svc = ProductContextService(store)
    identity = TrustedSessionIdentity(conversation_id="conv-b", customer_id="726588")
    result = svc.get_customer_products(
        identity,
        GetCustomerProductsQuery(product_type=ProductContextToolType.LOAN),
    )
    assert result["status"] == "OK"
    assert result["count"] >= 1
    assert all(p["product_type"] == "LOAN" for p in result["products"])


def test_get_customer_products_no_context(store: ReactiveSessionStore) -> None:
    store.create_session("conv-empty", "726588")
    svc = ProductContextService(store)
    identity = TrustedSessionIdentity(conversation_id="conv-empty", customer_id="726588")
    result = svc.get_customer_products(identity)
    assert result["status"] == "NO_CONTEXT"
    assert result["count"] == 0
