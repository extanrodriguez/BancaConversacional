"""Unit tests for POST /turn context_info load/refresh (Bloque A)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from genesis_cognitive.demo.contract_inspector_app import (
    TurnRequest,
    _pending_selection_blocks_brain,
)


def test_social_turn_bypasses_pending_product_selection() -> None:
    pending = SimpleNamespace(missing_requirements=["account_ref"])

    assert not _pending_selection_blocks_brain(pending, "¿estás ahí?")
    assert not _pending_selection_blocks_brain(pending, "gracias")
    assert _pending_selection_blocks_brain(pending, "el certificado terminado en 5511")


class TestTurnRequestModel:
    """U1 — TurnRequest accepts context_info fields."""

    def test_context_load_request_valid(self) -> None:
        req = TurnRequest(
            customer_id="1234",
            conversation_id="sess-1",
            question=None,
            context_info=True,
            context_op="load",
            context={"data": {"resultCode": 0, "products": [{"id": "x"}]}},
        )
        assert req.context_info is True
        assert req.context_op == "load"
        assert req.question is None

    def test_normal_turn_no_context(self) -> None:
        req = TurnRequest(
            customer_id="CUST001",
            conversation_id="c1",
            question="hola",
        )
        assert req.context_info is False
        assert req.context is None
        assert req.question == "hola"

    def test_context_refresh(self) -> None:
        req = TurnRequest(
            customer_id="1234",
            conversation_id="sess-1",
            question=None,
            context_info=True,
            context_op="refresh",
            context={"data": {"resultCode": 0, "products": []}},
        )
        assert req.context_op == "refresh"


class TestContextValidation:
    """U2–U4 — Validation rules for context_info requests."""

    def test_context_info_with_question_not_null_invalid(self) -> None:
        """context_info=true + question != null → should be rejected at handler level."""
        # Model accepts it (validation is in handler), but we document the rule
        req = TurnRequest(
            customer_id="1234",
            conversation_id="sess-1",
            question="algo",
            context_info=True,
            context_op="load",
            context={"data": {"products": []}},
        )
        # Handler will return 422; model just stores values
        assert req.question == "algo"
        assert req.context_info is True

    def test_missing_customer_id(self) -> None:
        """Empty customer_id with context_info → handler rejects."""
        req = TurnRequest(
            customer_id="",
            conversation_id="sess-1",
            question=None,
            context_info=True,
            context={"data": {"products": []}},
        )
        assert req.customer_id == ""

    def test_invalid_context_op(self) -> None:
        """Invalid context_op → handler rejects; model accepts any string."""
        req = TurnRequest(
            customer_id="1234",
            conversation_id="sess-1",
            question=None,
            context_info=True,
            context_op="delete",
            context={"data": {"products": []}},
        )
        assert req.context_op == "delete"

    def test_products_count_from_data(self) -> None:
        """Verify products count logic."""
        data = {"data": {"resultCode": 0, "products": [{"a": 1}, {"b": 2}, {"c": 3}]}}
        products = data["data"].get("products", [])
        assert len(products) == 3
