"""Pruebas ruta semántica V4 (azure_plan) con Azure simulado — no acredita Azure real."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from genesis_cognitive.brain.azure_plan_adapter import (
    interpretation_to_turn_plan,
    is_unequivocal_structured_shortcut,
)
from genesis_cognitive.brain.azure_plan_turn import merge_pending_tasks
from genesis_cognitive.brain.security_secrets import redact_secret_digits_for_logs
from genesis_cognitive.brain.semantic_mode import get_semantic_mode
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import ReactiveSessionStore, SessionState
from genesis_cognitive.decision.types import (
    DetectedEntities,
    SemanticAction,
    TurnInterpretation,
)
from genesis_cognitive.enums import (
    FreshnessState,
    InterpretationMode,
    OperationalState,
    SelectedRoute,
)
from genesis_cognitive.router.faq_guardrail import clear_faq_cache


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("GENESIS_FAQ_PATH", str(root / "data" / "kb_faq_vf01.json"))
    monkeypatch.setenv("GENESIS_AZURE_BRAIN", "0")
    monkeypatch.setenv("GENESIS_SEMANTIC_MODE", "azure_plan")
    monkeypatch.setenv("GENESIS_SESSION_BACKEND", "memory")
    clear_faq_cache()
    yield
    clear_faq_cache()


def _interp(*actions: SemanticAction, mode: InterpretationMode | None = None):
    acts = list(actions)
    if mode is None:
        mode = (
            InterpretationMode.MULTI_INDEPENDENT
            if len(acts) > 1
            else InterpretationMode.SINGLE
        )
    return TurnInterpretation(
        mode=mode,
        actions=acts,
        clarifications=[],
        unsupported_segments=[],
    )


def _action(seq: int, intent: str, account_ref: str | None = None, **kw):
    ents: dict = {}
    if account_ref is not None:
        ents["account_ref"] = account_ref
    for k in ("currency", "knowledge_topic", "amount", "source_account_ref", "destination_account_ref"):
        if k in kw and kw[k] is not None:
            ents[k] = kw[k]
    route = (
        SelectedRoute.BUSINESS_RAG
        if "KNOWLEDGE" in intent
        else SelectedRoute.PERSONAL_READ
    )
    missing = [] if (account_ref or "KNOWLEDGE" in intent) else ["account_ref"]
    return SemanticAction(
        sequence=seq,
        intent_id=intent,
        capability_candidate=intent.replace("_READ", "").replace("_QUERY", ""),
        selected_route=route,
        detected_entities=DetectedEntities(**ents),
        missing_requirements=missing,
        depends_on=[],
        confidence=0.9,
    )


def test_semantic_mode_selector(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GENESIS_SEMANTIC_MODE", "azure_plan")
    assert get_semantic_mode() == "azure_plan"
    monkeypatch.setenv("GENESIS_SEMANTIC_MODE", "legacy")
    assert get_semantic_mode() == "legacy"


def test_adapter_maps_multi_actions_to_plan():
    interp = _interp(
        _action(1, "BUSINESS_KNOWLEDGE_QUERY", knowledge_topic="vision"),
        _action(2, "ACCOUNT_BALANCE_READ", account_ref="A1"),
    )
    plan = interpretation_to_turn_plan(interp, "visión del banco y saldo de A1")
    assert plan.source == "azure_plan"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].domain == "institutional"
    assert plan.tasks[1].object == "account"
    assert "balance" in plan.tasks[1].fields or "available" in plan.tasks[1].fields
    assert "vision" not in plan.tasks[1].fields


def test_shortcut_not_triggered_by_mission_word_in_compound():
    ok, reason = is_unequivocal_structured_shortcut(
        "dime la misión y el disponible de mi cuenta", None,
    )
    assert ok is False
    assert reason == "open_language"


def test_alphanumeric_secret_redaction():
    raw = "mi pin es Ab12xy ahora"
    safe = redact_secret_digits_for_logs(raw)
    assert "Ab12xy" not in safe
    assert "***" in safe


def test_merge_pending_keeps_other_family():
    existing = [
        {"task_id": "t1", "object": "loan", "fields": ["rate"]},
        {"task_id": "t2", "object": "bank", "fields": ["mision"]},
    ]
    incoming = [{"task_id": "t1", "object": "loan", "fields": ["rate"], "entity": "L2"}]
    merged = merge_pending_tasks(existing, incoming, clear_ids=set())
    ids = {p["task_id"] for p in merged}
    assert ids == {"t1", "t2"}


def _make_app(store, resolver_result):
    from genesis_cognitive.context.adapters.in_memory_capability_context import (
        InMemoryCapabilityContextProvider,
    )
    from genesis_cognitive.context.adapters.in_memory_conversation_context import (
        InMemoryConversationContextProvider,
    )
    from genesis_cognitive.context.adapters.in_memory_pending_operation_context import (
        InMemoryPendingOperationContextProvider,
    )
    from genesis_cognitive.context.adapters.in_memory_portfolio_context import (
        InMemoryPortfolioContextProvider,
    )
    from genesis_cognitive.context.context_assembler import ContextAssembler
    from genesis_cognitive.context.context_types import PortfolioContext
    from genesis_cognitive.context.types import PortfolioProduct, PortfolioSnapshot
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
    from genesis_cognitive.demo.contract_inspector_app import create_app
    from genesis_cognitive.model_input.model_input_builder import ModelInputBuilder
    from genesis_cognitive.validation.input_validator import InputValidator

    now = datetime.now(tz=UTC)
    portfolio_data = {
        "demo-customer": PortfolioContext(
            snapshot=PortfolioSnapshot(
                version="t",
                generated_at=now,
                fresh_until=now + timedelta(minutes=5),
                freshness_state=FreshnessState.FRESH,
                products=(
                    PortfolioProduct(
                        product_ref="X",
                        product_type="SAVINGS",
                        label="A",
                        alias="a",
                        currency="DOP",
                        operational_state=OperationalState.ACTIVE,
                        recent_balance=Decimal("1"),
                        known_reserved_amount=Decimal("0"),
                        balance_as_of=now,
                    ),
                ),
            )
        )
    }
    resolver = MagicMock()
    # resolve used by legacy paths
    resolver.resolve = AsyncMock(return_value=resolver_result.interpretation)
    call_rec = MagicMock(name="proposer", duration_ms=12, deployment="test-deploy")
    call_rec.name = "proposer"
    call_rec.duration_ms = 12
    call_rec.deployment = "test-deploy"
    result = MagicMock(
        interpretation=resolver_result.interpretation,
        status="VALID_CONTRACT",
        non_operational_message=None,
        initial_proposal=None,
        verified_proposal=None,
        call_records=[call_rec],
    )
    resolver.resolve_full = AsyncMock(return_value=result)
    return create_app(
        resolver=resolver,
        gate=SemanticContractGate(),
        input_validator=InputValidator(),
        context_assembler=ContextAssembler(
            InMemoryConversationContextProvider(),
            InMemoryPortfolioContextProvider(data=portfolio_data),
            InMemoryPendingOperationContextProvider(),
            InMemoryCapabilityContextProvider(CapabilityCatalog()),
        ),
        model_input_builder=ModelInputBuilder(),
        azure_model="test-model",
        prompt_version="test-prompt-v4",
        db_path=None,
        session_store=store,
    ), resolver


def test_turn_azure_plan_vision_and_keeps_focus(monkeypatch: pytest.MonkeyPatch):
    """Recorrido: visión institucional con Azure simulado; inference_count > 0."""
    snap = CustomerContextSnapshot(
        customer_id="V4", display_name="Ana", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="A1", product_type="CHECKING", alias="Corriente",
                currency="USD", status="active", available_balance=Decimal("50"),
                ledger_balance=Decimal("60"),
            ),
        ),
        loans=(),
    )
    store = ReactiveSessionStore()
    store.put_snapshot("V4", snap, mark_fetched_now=True)
    store.put_session("c-v4", SessionState(
        customer_id="V4", snapshot=snap, snapshot_source_fetched_at=time.time(),
        product_focus=None,
    ))
    interp = _interp(_action(1, "BUSINESS_KNOWLEDGE_QUERY", knowledge_topic="vision"))
    # Wrap interpretation in a simple namespace
    ns = MagicMock(interpretation=interp)
    app, resolver = _make_app(store, ns)
    client = TestClient(app)
    r = client.post("/turn", json={
        "question": "Dime la visión del banco",
        "conversation_id": "c-v4",
        "customer_id": "V4",
    })
    assert r.status_code == 200
    body = r.json()
    audit = body.get("audit") or {}
    assert (audit.get("inference_count") or 0) >= 1
    assert audit.get("semantic_mode") == "azure_plan"
    assert resolver.resolve_full.await_count == 1
    # Respuesta no vacía (FAQ o gap explícito)
    assert (body.get("client_response") or body.get("reply") or "").strip()


def test_turn_azure_plan_available_clarifies_without_entity():
    snap = CustomerContextSnapshot(
        customer_id="V4b", display_name="Ana", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="A1", product_type="SAVINGS", alias="Ahorros",
                currency="DOP", status="active", available_balance=Decimal("10"),
                ledger_balance=Decimal("11"),
            ),
            ProductSnapshot(
                product_id="A2", product_type="CHECKING", alias="Corriente",
                currency="USD", status="active", available_balance=Decimal("20"),
                ledger_balance=Decimal("21"),
            ),
        ),
        loans=(),
    )
    store = ReactiveSessionStore()
    store.put_snapshot("V4b", snap, mark_fetched_now=True)
    store.put_session("c-v4b", SessionState(
        customer_id="V4b", snapshot=snap, snapshot_source_fetched_at=time.time(),
    ))
    # Sin account_ref → needs clarification en el adaptador
    interp = _interp(_action(1, "ACCOUNT_BALANCE_READ", account_ref=None))
    ns = MagicMock(interpretation=interp)
    app, resolver = _make_app(store, ns)
    client = TestClient(app)
    r = client.post("/turn", json={
        "question": "¿Con cuánto puedo contar?",
        "conversation_id": "c-v4b",
        "customer_id": "V4b",
    })
    assert r.status_code == 200
    body = r.json()
    assert resolver.resolve_full.await_count == 1
    # Debe aclarar o listar — no inventar un total
    text = (body.get("client_response") or body.get("reply") or "").lower()
    assert "30" not in text.replace(",", "")  # no sumar DOP+USD


def test_azure_failure_not_labeled_as_heuristic_success(monkeypatch: pytest.MonkeyPatch):
    snap = CustomerContextSnapshot(
        customer_id="V4e", display_name="Ana", default_currency="DOP",
        products=(), loans=(),
    )
    store = ReactiveSessionStore()
    store.put_snapshot("V4e", snap, mark_fetched_now=True)
    store.put_session("c-v4e", SessionState(customer_id="V4e", snapshot=snap))
    interp = _interp(_action(1, "BUSINESS_KNOWLEDGE_QUERY"))
    ns = MagicMock(interpretation=interp)
    app, resolver = _make_app(store, ns)
    resolver.resolve_full = AsyncMock(side_effect=RuntimeError("simulated_azure_down"))
    client = TestClient(app)
    r = client.post("/turn", json={
        "question": "misión del banco",
        "conversation_id": "c-v4e",
        "customer_id": "V4e",
    })
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "PROVIDER_ERROR"
    audit = body.get("audit") or {}
    assert (audit.get("inference_count") or 0) == 0
    traces = audit.get("decision_trace") or []
    out = (traces[0].get("output") if traces else {}) or {}
    assert out.get("not_heuristic_fallback") is True


def test_legacy_mode_still_uses_heuristic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GENESIS_SEMANTIC_MODE", "legacy")
    snap = CustomerContextSnapshot(
        customer_id="L1", display_name="Ana", default_currency="DOP",
        products=(), loans=(),
    )
    store = ReactiveSessionStore()
    store.put_snapshot("L1", snap, mark_fetched_now=True)
    store.put_session("c-l1", SessionState(customer_id="L1", snapshot=snap))
    interp = _interp(_action(1, "BUSINESS_KNOWLEDGE_QUERY"))
    ns = MagicMock(interpretation=interp)
    app, resolver = _make_app(store, ns)
    client = TestClient(app)
    r = client.post("/turn", json={
        "question": "misión del banco",
        "conversation_id": "c-l1",
        "customer_id": "L1",
    })
    assert r.status_code == 200
    # En legacy, resolve_full no debe ser el intérprete primario de misión
    assert resolver.resolve_full.await_count == 0
