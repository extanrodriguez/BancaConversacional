"""Cierre pendientes 1C: CAS HTTP E2E, tasa contextual, preguntas mixtas."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import (
    ProductFocus,
    ReactiveSessionStore,
    SessionConflictError,
    SessionState,
)
from genesis_cognitive.enums import FreshnessState, InterpretationMode, OperationalState, SelectedRoute
from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail, clear_faq_cache
from genesis_cognitive.router.field_guardrails import run_field_fastpath
from genesis_cognitive.router.rate_context_guardrail import (
    apply_mixed_personal_knowledge_guardrail,
    apply_personal_rate_guardrail,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _env_faq(monkeypatch):
    monkeypatch.setenv("GENESIS_FAQ_PATH", str(PROJECT_ROOT / "data" / "kb_faq_vf01.json"))
    monkeypatch.setenv(
        "GENESIS_FAQ_OVERLAY_PATH",
        str(PROJECT_ROOT / "data" / "kb_faq_overlay_fase1.json"),
    )
    monkeypatch.setenv("GENESIS_AZURE_BRAIN", "0")
    clear_faq_cache()
    from genesis_cognitive.router import rate_context_guardrail as rcg

    rcg.set_definition_evidence_override(
        lambda: rcg._SYNTHETIC_RATE_DEFINITION,
    )
    yield
    rcg.set_definition_evidence_override(None)
    clear_faq_cache()


def _loan(
    pid: str = "LOAN1",
    *,
    rate: str = "12.5",
    last4: str = "1111",
) -> tuple[ProductSnapshot, LoanSnapshot]:
    p = ProductSnapshot(
        product_id=pid,
        product_type="LOAN",
        alias="Préstamo",
        currency="DOP",
        status="active",
        last_four=last4,
    )
    ln = LoanSnapshot(
        product_id=pid,
        loan_type="PERSONAL",
        installment_amount=Decimal("1000"),
        annual_interest_rate=Decimal(rate),
        outstanding_principal=Decimal("50000"),
        delinquency_days=0,
        next_due_date="2026-10-01",
        last_four=last4,
    )
    return p, ln


def _dap(pid: str = "DAP1", *, rate: str = "8.15") -> ProductSnapshot:
    return ProductSnapshot(
        product_id=pid,
        product_type="TERM_DEPOSIT",
        alias="Certificado",
        currency="DOP",
        status="active",
        interest_rate=Decimal(rate),
        last_four=pid[-4:],
        maturity_date="2026-09-19",
    )


def _snap(
    *products: ProductSnapshot,
    loans: tuple[LoanSnapshot, ...] = (),
    cid: str = "SYN-RATE",
) -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id=cid,
        display_name="Cliente Sintetico",
        default_currency="DOP",
        products=products,
        loans=loans,
    )


def _make_app(store: ReactiveSessionStore, snap: CustomerContextSnapshot):
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
    from genesis_cognitive.decision.types import DetectedEntities, SemanticAction, TurnInterpretation
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
    interp = TurnInterpretation(
        mode=InterpretationMode.SINGLE,
        actions=[
            SemanticAction(
                sequence=1,
                intent_id="ACCOUNT_BALANCE_READ",
                capability_candidate="ACCOUNT_BALANCE",
                selected_route=SelectedRoute.PERSONAL_READ,
                detected_entities=DetectedEntities(account_ref=None),
                missing_requirements=["account_ref"],
                depends_on=[],
                confidence=0.5,
            )
        ],
        clarifications=[],
        unsupported_segments=[],
    )
    resolver.resolve = AsyncMock(return_value=interp)
    resolver.resolve_full = AsyncMock(
        return_value=MagicMock(
            interpretation=interp,
            initial_proposal=None,
            verified_proposal=None,
            non_operational_message=None,
        )
    )
    app = create_app(
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
        prompt_version="test-prompt",
        db_path=None,
        session_store=store,
    )
    store.put_snapshot(snap.customer_id, snap, mark_fetched_now=True)
    return app


def _seed(store: ReactiveSessionStore, conv: str, snap: CustomerContextSnapshot) -> None:
    store.put_snapshot(snap.customer_id, snap, mark_fetched_now=True)
    store.put_session(
        conv,
        SessionState(
            customer_id=snap.customer_id,
            snapshot=snap,
            snapshot_source_fetched_at=time.time(),
        ),
    )


# ---------------------------------------------------------------------------
# Tasa contextual (sin overfit a préstamo)
# ---------------------------------------------------------------------------


def test_rate_loan_only_no_other_rate_product() -> None:
    lp, ln = _loan()
    snap = _snap(lp, loans=(ln,))
    out = apply_personal_rate_guardrail(snap, "¿Cuál es mi tasa?", None)
    assert out is not None
    assert out[0] == "VALID_CONTRACT"
    assert "12.5" in (out[2] or "")
    assert out[1][0]["intent_id"] == "LOAN_DETAIL_READ"


def test_rate_dap_only_no_loan() -> None:
    snap = _snap(_dap())
    out = apply_personal_rate_guardrail(snap, "¿Cuál es mi tasa?", None)
    assert out is not None
    assert out[0] == "VALID_CONTRACT"
    assert "8.15" in (out[2] or "")
    assert out[1][0]["intent_id"] == "TERM_DEPOSIT_DETAIL_READ"


def test_rate_loan_and_dap_no_focus_clarifies() -> None:
    lp, ln = _loan()
    snap = _snap(lp, _dap(), loans=(ln,))
    out = apply_personal_rate_guardrail(snap, "¿Cuál es mi tasa?", None)
    assert out is not None
    assert out[0] == "CLARIFICATION_REQUIRED"
    low = (out[2] or "").lower()
    assert "préstamo" in low or "prestamo" in low
    assert "depósito" in low or "deposito" in low or "plazo" in low


def test_rate_loan_and_dap_with_focus_uses_focus() -> None:
    lp, ln = _loan()
    snap = _snap(lp, _dap(), loans=(ln,))
    sess = SessionState(customer_id=snap.customer_id, snapshot=snap)
    sess.product_focus = ProductFocus(
        kind="TERM_DEPOSIT",
        product_id="DAP1",
        intent_id="TERM_DEPOSIT_DETAIL_READ",
    )
    out = apply_personal_rate_guardrail(snap, "¿Cuál es mi tasa?", sess)
    assert out is not None
    assert out[0] == "VALID_CONTRACT"
    assert "8.15" in (out[2] or "")
    assert out[1][0]["detected_entities"]["account_ref"] == "DAP1"


def test_rate_multiple_loans_clarifies() -> None:
    p1, l1 = _loan("LOAN1", rate="10", last4="1111")
    p2, l2 = _loan("LOAN2", rate="14", last4="2222")
    snap = _snap(p1, p2, loans=(l1, l2))
    out = apply_personal_rate_guardrail(snap, "¿Cuál es mi tasa?", None)
    assert out is not None
    assert out[0] == "CLARIFICATION_REQUIRED"


def test_que_significa_tasa_is_knowledge_not_personal() -> None:
    lp, ln = _loan()
    snap = _snap(lp, loans=(ln,))
    assert apply_personal_rate_guardrail(snap, "¿Qué significa tasa?", None) is None
    faq = apply_faq_guardrail(snap, "¿Qué significa tasa de interés?", None)
    assert faq is not None
    assert faq[1][0]["intent_id"] == "BUSINESS_KNOWLEDGE_QUERY"


def test_fastpath_rate_scenarios_wired() -> None:
    lp, ln = _loan()
    both = _snap(lp, _dap(), loans=(ln,))
    hit = run_field_fastpath(both, "¿Cuál es mi tasa?", None)
    assert hit is not None
    assert hit[4] == "personal_rate"
    assert hit[0] == "CLARIFICATION_REQUIRED"


# ---------------------------------------------------------------------------
# Preguntas mixtas
# ---------------------------------------------------------------------------


def test_mixed_loan_rate_and_definition_keeps_both() -> None:
    lp, ln = _loan()
    snap = _snap(lp, loans=(ln,))
    q = "¿Cuál es la tasa de mi préstamo y qué significa?"
    out = apply_mixed_personal_knowledge_guardrail(snap, q, None)
    assert out is not None
    assert out[0] == "VALID_CONTRACT"
    text = out[2] or ""
    assert "12.5" in text
    assert "significa" in text.lower() or "tasa" in text.lower()
    # No inventar vacío: hay evidencia FAQ o sintético marcado
    assert "evidencia-sintetica-test" in text or "tarifari" in text.lower() or "porcentaje" in text.lower()


def test_mixed_multiple_loans_clarifies_without_dropping_definition() -> None:
    p1, l1 = _loan("LOAN1", rate="10", last4="1111")
    p2, l2 = _loan("LOAN2", rate="14", last4="2222")
    snap = _snap(p1, p2, loans=(l1, l2))
    sess = SessionState(customer_id=snap.customer_id, snapshot=snap)
    q = "¿Cuál es la tasa de mi préstamo y qué significa?"
    out = apply_mixed_personal_knowledge_guardrail(snap, q, sess)
    assert out is not None
    assert out[0] == "CLARIFICATION_REQUIRED"
    text = (out[2] or "").lower()
    assert "significa" in text or "explic" in text
    assert sess.pending_action is not None
    assert "mixed_pending_definition" in (sess.pending_action.detected_entities or {})


# ---------------------------------------------------------------------------
# Concurrencia HTTP /inspect (store in-memory simulado; Redis no configurado)
# ---------------------------------------------------------------------------


def test_mixed_without_evidence_declares_missing_definition(monkeypatch) -> None:
    """Sin FAQ útil ni fixture: conserva tasa y declara definición no disponible."""
    from genesis_cognitive.router import rate_context_guardrail as rcg

    rcg.set_definition_evidence_override(None)
    monkeypatch.setattr(rcg, "match_faq", lambda *_a, **_k: None)
    lp, ln = _loan()
    snap = _snap(lp, loans=(ln,))
    q = "¿Cuál es la tasa de mi préstamo y qué significa?"
    out = apply_mixed_personal_knowledge_guardrail(snap, q, None)
    assert out is not None
    assert "12.5" in (out[2] or "")
    low = (out[2] or "").lower()
    assert "no pude resolver" in low or "no disponible" in low or "evidencia" in low


@pytest.mark.asyncio
async def test_http_concurrent_turns_same_session_with_contention() -> None:
    """Dos corutinas /inspect: instrumentación fuerza solape en sección crítica."""
    import httpx
    from genesis_cognitive.context.conversation_gate import (
        ConversationGate,
        reset_conversation_gate_for_tests,
    )

    lp, ln = _loan()
    snap = _snap(
        ProductSnapshot(
            "CA1", "SAVINGS", "Ahorros", "DOP", "active",
            available_balance=Decimal("100"), ledger_balance=Decimal("100"),
        ),
        lp,
        loans=(ln,),
        cid="HTTP-CONC",
    )
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    conv = "http-conc-same"
    _seed(store, conv, snap)

    gate = ConversationGate(redis_client=None, redis_required=False, lock_ttl_s=15)
    gate.test_hold_delay_s = 0.2  # primer holder permanece en sección crítica
    reset_conversation_gate_for_tests(gate)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async def turn(tag: str) -> tuple[int, str]:
                resp = await client.post(
                    "/inspect",
                    json={
                        "question": f"¿Cuál es mi tasa? {tag}",
                        "conversation_id": conv,
                        "customer_id": snap.customer_id,
                    },
                )
                body = resp.json()
                return resp.status_code, str(body.get("status") or "")

            r1, r2 = await asyncio.gather(turn("a"), turn("b"))
        results = [r1, r2]
        assert all(code == 200 for code, _ in results)
        assert all(st != "SESSION_CONFLICT" for _, st in results)
        assert any(
            st in ("VALID_CONTRACT", "CLARIFICATION_REQUIRED", "SESSION_BUSY")
            for _, st in results
        )
        # Con delay en sección crítica, el segundo espera o recibe busy
        sess = store.get_session(conv)
        assert sess is not None
    finally:
        reset_conversation_gate_for_tests(None)


def test_http_two_sessions_same_client_isolated() -> None:
    lp, ln = _loan()
    snap = _snap(lp, loans=(ln,), cid="SAME-CLI")
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    client = TestClient(app)
    _seed(store, "sess-a", snap)
    _seed(store, "sess-b", snap)
    r1 = client.post(
        "/inspect",
        json={"question": "¿Cuál es mi tasa?", "conversation_id": "sess-a", "customer_id": "SAME-CLI"},
    )
    r2 = client.post(
        "/inspect",
        json={"question": "¿Qué significa tasa de interés?", "conversation_id": "sess-b", "customer_id": "SAME-CLI"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    a = store.get_session("sess-a")
    b = store.get_session("sess-b")
    assert a is not None and b is not None
    assert a.history != b.history


def test_http_distinct_clients_isolated() -> None:
    p1, l1 = _loan("L-A", rate="11")
    p2, l2 = _loan("L-B", rate="19")
    snap_a = _snap(p1, loans=(l1,), cid="CLI-A")
    snap_b = _snap(p2, loans=(l2,), cid="CLI-B")
    store = ReactiveSessionStore()
    app = _make_app(store, snap_a)
    store.put_snapshot("CLI-B", snap_b, mark_fetched_now=True)
    client = TestClient(app)
    _seed(store, "c-a", snap_a)
    _seed(store, "c-b", snap_b)
    ra = client.post(
        "/inspect",
        json={"question": "¿Cuál es mi tasa?", "conversation_id": "c-a", "customer_id": "CLI-A"},
    )
    rb = client.post(
        "/inspect",
        json={"question": "¿Cuál es mi tasa?", "conversation_id": "c-b", "customer_id": "CLI-B"},
    )
    assert ra.status_code == 200 and rb.status_code == 200
    assert "11" in (ra.json().get("client_response") or "")
    assert "19" in (rb.json().get("client_response") or "")


@pytest.mark.asyncio
async def test_http_concurrent_session_create_same_conv() -> None:
    import httpx
    from genesis_cognitive.context.conversation_gate import (
        ConversationGate,
        reset_conversation_gate_for_tests,
    )

    store = ReactiveSessionStore()
    snap = _snap(_dap(), cid="CREATE-C")
    app = _make_app(store, snap)
    conv = "new-concurrent-conv"
    gate = ConversationGate(redis_client=None, redis_required=False)
    gate.test_hold_delay_s = 0.12
    reset_conversation_gate_for_tests(gate)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async def create_turn() -> tuple[int, str]:
                resp = await client.post(
                    "/inspect",
                    json={
                        "question": "¿Cuál es mi tasa?",
                        "conversation_id": conv,
                        "customer_id": snap.customer_id,
                    },
                )
                return resp.status_code, str(resp.json().get("status") or "")

            c1, c2 = await asyncio.gather(create_turn(), create_turn())
        assert all(c == 200 for c, _ in (c1, c2))
        assert "SESSION_CONFLICT" not in (c1[1], c2[1])
        sess = store.get_session(conv)
        assert sess is not None
    finally:
        reset_conversation_gate_for_tests(None)


def test_turn_endpoint_maps_busy_without_fake_valid_contract() -> None:
    """Consumidor productivo usa /turn; SESSION_BUSY no se reescribe a VALID_CONTRACT."""
    lp, ln = _loan()
    snap = _snap(lp, loans=(ln,), cid="TURN-BUSY")
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    client = TestClient(app)
    from genesis_cognitive.context.conversation_gate import (
        ConversationGate,
        reset_conversation_gate_for_tests,
    )
    from contextlib import asynccontextmanager

    class _NeverGate(ConversationGate):
        @asynccontextmanager
        async def hold(self, conversation_id: str, *, timeout_s: float = 25.0):
            yield {"acquired": False, "token": None, "still_owner": lambda: False}

    reset_conversation_gate_for_tests(_NeverGate())
    try:
        resp = client.post(
            "/turn",
            json={
                "question": "¿Cuál es mi tasa?",
                "conversation_id": "turn-busy-1",
                "customer_id": snap.customer_id,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "SESSION_BUSY"
        reply = (body.get("reply") or (body.get("app_channel") or {}).get("client_response") or "")
        assert isinstance(reply, str) and reply.strip()
    finally:
        reset_conversation_gate_for_tests(None)


def test_context_info_busy_returns_503_not_loaded() -> None:
    """LoadInitialContextAsync solo falla en no-2xx; busy no debe parecer CONTEXT_LOADED."""
    store = ReactiveSessionStore()
    snap = _snap(_dap(), cid="CTX-BUSY")
    app = _make_app(store, snap)
    client = TestClient(app)
    from genesis_cognitive.context.conversation_gate import (
        ConversationGate,
        reset_conversation_gate_for_tests,
    )
    from contextlib import asynccontextmanager

    class _NeverGate(ConversationGate):
        @asynccontextmanager
        async def hold(self, conversation_id: str, *, timeout_s: float = 25.0):
            yield {"acquired": False, "token": None, "still_owner": lambda: False}

    reset_conversation_gate_for_tests(_NeverGate())
    try:
        resp = client.post(
            "/turn",
            json={
                "question": None,
                "conversation_id": "ctx-busy-1",
                "customer_id": snap.customer_id,
                "context_info": True,
                "context_op": "load",
                "context": {"data": {"products": []}},
            },
        )
        assert resp.status_code == 503
        body = resp.json()
        assert body.get("status") == "CONTEXT_LOAD_BUSY"
        assert body.get("persisted") is False
        assert body.get("status") != "CONTEXT_LOADED"
    finally:
        reset_conversation_gate_for_tests(None)


@pytest.mark.asyncio
async def test_asyncio_lock_excludes_same_thread_coroutines() -> None:
    """asyncio.Lock sí excluye corutinas concurrentes; RLock no bastaría."""
    from genesis_cognitive.context.conversation_gate import ConversationGate

    gate = ConversationGate(redis_client=None, redis_required=False, lock_ttl_s=10)
    gate.test_hold_delay_s = 0.15
    order: list[str] = []

    async def worker(tag: str) -> None:
        async with gate.hold("same-conv", timeout_s=2.0) as st:
            assert st["acquired"]
            order.append(f"{tag}-enter")
            await asyncio.sleep(0.05)
            order.append(f"{tag}-exit")

    await asyncio.gather(worker("a"), worker("b"))
    # Sin solape de secciones: enter/exit de uno completo antes del otro enter
    assert order in (
        ["a-enter", "a-exit", "b-enter", "b-exit"],
        ["b-enter", "b-exit", "a-enter", "a-exit"],
    )


@pytest.mark.skip(
    reason=(
        "Redis real multi-proceso: requiere Docker Engine activo. "
        "Iniciar Docker Desktop y ejecutar works/REDIS_CONCURRENCY_PROCEDURE_1C.md"
    ),
)
def test_redis_multiprocess_turn_pending_until_docker() -> None:
    raise AssertionError("no declarar éxito Redis sin Docker Engine")


def test_store_create_session_cas_conflict() -> None:
    store = ReactiveSessionStore()
    store.create_session("c1", "U1")
    with pytest.raises(SessionConflictError):
        store.create_session("c1", "U1")


def test_redis_backend_not_configured_in_this_run() -> None:
    """Documenta: estas pruebas usan ReactiveSessionStore in-memory (simulado)."""
    assert not os.getenv("GENESIS_REDIS_URL")
    assert not os.getenv("REDIS_URL")
