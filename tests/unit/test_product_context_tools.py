"""execute_get_customer_products — ignores LLM customer_id."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from genesis_cognitive.agents.product_context_tools import execute_get_customer_products
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import ReactiveSessionStore


def test_tool_ignores_llm_customer_id() -> None:
    store = ReactiveSessionStore(session_ttl_s=3600.0)
    sess = store.create_session("conv-tool", "111")
    sess.snapshot = CustomerContextSnapshot(
        customer_id="111",
        display_name="A",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="CA1",
                product_type="SAVINGS",
                alias=None,
                currency="DOP",
                status="active",
            ),
        ),
        loans=(),
    )
    store.put_session("conv-tool", sess)

    result = execute_get_customer_products(
        store,
        conversation_id="conv-tool",
        customer_id_hint="111",
        arguments={"product_type": "ACCOUNT"},
        ignore_llm_customer_id="999999",
    )
    assert result["status"] == "OK"
    assert result["count"] == 1

    bad = execute_get_customer_products(
        store,
        conversation_id="conv-tool",
        customer_id_hint="999999",
        arguments={"product_type": "ALL"},
    )
    assert bad["status"] == "FORBIDDEN"
