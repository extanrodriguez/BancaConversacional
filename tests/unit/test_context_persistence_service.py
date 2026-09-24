"""ContextPersistenceService — WRITE PATH orchestrator context."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from genesis_cognitive.context.context_persistence_service import ContextPersistenceService
from genesis_cognitive.context.reactive_store import ReactiveSessionStore
from tests.unit.test_core_portfolio_mapper import FIXTURE_CA_TC


@pytest.fixture
def store() -> ReactiveSessionStore:
    return ReactiveSessionStore(session_ttl_s=3600.0)


def test_persist_orchestrator_context_load(store: ReactiveSessionStore) -> None:
    svc = ContextPersistenceService(store)
    ctx_data = FIXTURE_CA_TC
    out = svc.persist_orchestrator_context(
        customer_id="726588",
        conversation_id="persist-test-1",
        ctx_data=ctx_data,
        op="load",
    )
    assert out["status"] == "CONTEXT_LOADED"
    assert out["source"] == "ORCHESTRATOR"
    assert out["products_count"] >= 1
    sess = store.get_session("persist-test-1")
    assert sess is not None
    assert sess.snapshot is not None
    assert sess.snapshot.customer_id == "726588"


def test_validate_context_payload_missing_data() -> None:
    with pytest.raises(ValueError, match="context.data"):
        ContextPersistenceService.validate_context_payload({"foo": 1})
