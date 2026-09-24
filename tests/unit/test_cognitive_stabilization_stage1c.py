"""Etapa 1C — interferencia FAQ con corpus real, elegibilidad y CAS/QA.

- FAQ: corpus + overlay reales del repo (NO mock de apply_faq_guardrail).
- Continuity: resolutor real (NO mock).
- Sí se mockean Azure OpenAI y servicios externos (Foundry/Core remoto).
- /inspect vía create_app + ReactiveSessionStore (sin tocar contract_inspector_app).
- Prueba QA Azure real: skip + harness documentado (sin ejecutar).
"""

from __future__ import annotations

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
    ReactiveSessionStore,
    SessionConflictError,
    SessionState,
)
from genesis_cognitive.enums import FreshnessState, InterpretationMode, OperationalState, SelectedRoute
from genesis_cognitive.router.faq_guardrail import (
    apply_faq_guardrail,
    clear_faq_cache,
    is_mixed_personal_and_knowledge_question,
    is_personal_portfolio_faq_blocked,
    match_faq,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAQ_PATH = PROJECT_ROOT / "data" / "kb_faq_vf01.json"
OVERLAY_PATH = PROJECT_ROOT / "data" / "kb_faq_overlay_fase1.json"


@pytest.fixture(autouse=True)
def _real_faq_corpus(monkeypatch):
    assert FAQ_PATH.is_file(), f"falta corpus FAQ: {FAQ_PATH}"
    assert OVERLAY_PATH.is_file(), f"falta overlay FAQ: {OVERLAY_PATH}"
    monkeypatch.setenv("GENESIS_FAQ_PATH", str(FAQ_PATH))
    monkeypatch.setenv("GENESIS_FAQ_OVERLAY_PATH", str(OVERLAY_PATH))
    monkeypatch.delenv("GENESIS_AZURE_BRAIN", raising=False)
    monkeypatch.setenv("GENESIS_AZURE_BRAIN", "0")
    clear_faq_cache()
    yield
    clear_faq_cache()


def _synth_snap(customer_id: str = "SYN-1C") -> CustomerContextSnapshot:
    """Portafolio sintético dual DOP/USD + préstamo + TC (sin PII real)."""
    return CustomerContextSnapshot(
        customer_id=customer_id,
        display_name="Cliente Sintetico",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="CA1001DOP",
                product_type="SAVINGS",
                alias="Ahorros pesos",
                currency="DOP",
                status="active",
                available_balance=Decimal("15000.00"),
                ledger_balance=Decimal("15200.00"),
                last_four="1001",
            ),
            ProductSnapshot(
                product_id="CA2002USD",
                product_type="SAVINGS",
                alias="Ahorros dólares",
                currency="USD",
                status="active",
                available_balance=Decimal("320.50"),
                ledger_balance=Decimal("350.00"),
                last_four="2002",
            ),
            ProductSnapshot(
                product_id="LOAN27615",
                product_type="LOAN",
                alias="Préstamo personal",
                currency="DOP",
                status="active",
                last_four="7615",
            ),
            ProductSnapshot(
                product_id="TC6582",
                product_type="CREDIT_CARD",
                alias="Visa Sintetica",
                currency="DOP",
                status="active",
                card_mask="****6582",
                last_four="6582",
                credit_limit=Decimal("25000"),
                available_purchases_domestic=Decimal("12000"),
                cutoff_day=15,
            ),
        ),
        loans=(
            LoanSnapshot(
                product_id="LOAN27615",
                loan_type="PERSONAL",
                installment_amount=Decimal("4500"),
                annual_interest_rate=Decimal("18.5"),
                outstanding_principal=Decimal("85000"),
                delinquency_days=0,
                next_due_date="2026-10-05",
                last_four="7615",
            ),
        ),
    )


def _make_app(store: ReactiveSessionStore, *, snap: CustomerContextSnapshot | None = None):
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
                version="test-v1",
                generated_at=now,
                fresh_until=now + timedelta(minutes=5),
                freshness_state=FreshnessState.FRESH,
                products=(
                    PortfolioProduct(
                        product_ref="CA1001DOP",
                        product_type="SAVINGS",
                        label="Ahorros",
                        alias="pesos",
                        currency="DOP",
                        operational_state=OperationalState.ACTIVE,
                        recent_balance=Decimal("15000"),
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
    if snap is not None:
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


def _inspect(client: TestClient, question: str, conv: str, customer_id: str) -> dict[str, Any]:
    resp = client.post(
        "/inspect",
        json={"question": question, "conversation_id": conv, "customer_id": customer_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _trace_step(payload: dict[str, Any]) -> str:
    trace = payload.get("decision_trace") or []
    if not trace:
        return ""
    return str(trace[0].get("step") or "")


# ---------------------------------------------------------------------------
# 1) Reproducción de interferencia (corpus real, sin mock FAQ)
# ---------------------------------------------------------------------------


def test_faq_corpus_would_steal_personal_disponible_without_eligibility() -> None:
    """Sin gate de elegibilidad, match textual FAQ gana con topic ajeno."""
    hit = match_faq("¿Cuánto tengo disponible?")
    assert hit is not None
    assert float(hit.get("score") or 0) >= 0.78
    topic = str(hit.get("topic") or "").lower()
    # Corpus real: no es respuesta de saldo personal
    assert "disponible" not in topic or "saldo" not in topic
    assert is_personal_portfolio_faq_blocked("¿Cuánto tengo disponible?") is True
    # Con elegibilidad, apply_faq no consume
    assert apply_faq_guardrail(_synth_snap(), "¿Cuánto tengo disponible?", None) is None


def test_faq_eligibility_matrix_personal_definition_mixed() -> None:
    snap = _synth_snap()
    session = SessionState(customer_id=snap.customer_id, snapshot=snap)

    cases = [
        ("¿Cuánto tengo disponible?", True, False, None),
        ("¿Y el disponible de esa cuenta?", True, False, None),
        ("¿Cuál es mi tasa?", True, False, None),
        ("¿Cuándo corta mi tarjeta?", True, False, None),
        ("¿Qué significa tasa de interés?", False, False, "faq"),
        ("¿Qué es la fecha de corte?", False, False, "faq"),
        ("Dime mi saldo y qué significa disponible", False, True, None),
    ]
    for q, blocked, mixed, expect in cases:
        assert is_personal_portfolio_faq_blocked(q, session=session, snapshot=snap) is blocked, q
        assert is_mixed_personal_and_knowledge_question(q) is mixed, q
        out = apply_faq_guardrail(snap, q, session)
        if expect == "faq":
            assert out is not None, q
            assert out[1][0]["intent_id"] == "BUSINESS_KNOWLEDGE_QUERY"
            text = (out[2] or "").lower()
            if "tasa" in q.lower():
                assert "tasa" in text or "interés" in text or "interes" in text
            if "corte" in q.lower():
                assert "corte" in text
        else:
            assert out is None, f"FAQ no debió consumir: {q} -> {out}"


def test_definition_saldo_disponible_rejects_irrelevant_or_abstains() -> None:
    """Definición explícita: o hit relevante, o abstención (nunca topic Cargo/ajeno)."""
    q = "¿Qué significa saldo disponible?"
    assert is_personal_portfolio_faq_blocked(q) is False
    out = apply_faq_guardrail(_synth_snap(), q, None)
    if out is None:
        # Corpus sin entrada útil → Foundry/QA; no inventar
        hit = match_faq(q)
        if hit:
            topic = str(hit.get("topic") or "").lower()
            assert "cargo" not in topic
        return
    text = (out[2] or "").lower()
    assert "cargo" not in text
    assert any(s in text for s in ("disponible", "saldo", "monto", "fondos", "usar"))


def test_inspect_interference_cases_real_faq(monkeypatch) -> None:
    """Endpoint local: personales ≠ FAQ; definiciones = conocimiento."""
    # Foundry remoto: mock (servicio externo)
    import genesis_cognitive.rag.foundry_kb_agent as foundry_mod

    monkeypatch.setattr(
        foundry_mod,
        "ask_foundry_kb_agent",
        lambda *a, **k: None,
        raising=False,
    )

    snap = _synth_snap()
    store = ReactiveSessionStore()
    app = _make_app(store, snap=snap)
    client = TestClient(app)
    conv = "conv-1c-interference"
    _seed(store, conv, snap)

    r_avail = _inspect(client, "¿Cuánto tengo disponible?", conv, snap.customer_id)
    assert r_avail["status"] in ("CLARIFICATION_REQUIRED", "VALID_CONTRACT")
    step = _trace_step(r_avail)
    assert "faq" not in step.lower()
    assert "knowledge" not in step.lower() or "personal" in step.lower() or "fastpath" in step.lower()

    r_def_tasa = _inspect(client, "¿Qué significa tasa de interés?", conv, snap.customer_id)
    assert r_def_tasa["status"] == "VALID_CONTRACT"
    assert "faq" in _trace_step(r_def_tasa).lower() or "knowledge" in str(
        r_def_tasa.get("decision_trace")
    ).lower()
    assert "tasa" in (r_def_tasa["client_response"] or "").lower()

    r_def_corte = _inspect(client, "¿Qué es la fecha de corte?", conv, snap.customer_id)
    assert r_def_corte["status"] == "VALID_CONTRACT"
    assert "corte" in (r_def_corte["client_response"] or "").lower()
    assert "faq" in _trace_step(r_def_corte).lower() or "BUSINESS_KNOWLEDGE" in str(
        r_def_corte.get("actions")
    )

    r_mi_tasa = _inspect(client, "¿Cuál es mi tasa?", conv, snap.customer_id)
    text_tasa = (r_mi_tasa["client_response"] or "").lower()
    assert "depósitos a plazo" not in text_tasa and "depositos a plazo" not in text_tasa
    assert "faq" not in _trace_step(r_mi_tasa).lower()
    # Con préstamo sintético: tasa personal o clarificación de préstamo
    assert r_mi_tasa["status"] in ("VALID_CONTRACT", "CLARIFICATION_REQUIRED")
    if r_mi_tasa["status"] == "VALID_CONTRACT":
        assert "18.5" in (r_mi_tasa["client_response"] or "") or "tasa" in text_tasa

    r_corta = _inspect(client, "¿Cuándo corta mi tarjeta?", conv, snap.customer_id)
    assert "faq" not in _trace_step(r_corta).lower()
    assert r_corta["status"] in ("VALID_CONTRACT", "CLARIFICATION_REQUIRED")
    if r_corta["status"] == "VALID_CONTRACT":
        assert "15" in (r_corta["client_response"] or "") or "corte" in (
            r_corta["client_response"] or ""
        ).lower()


# ---------------------------------------------------------------------------
# 3) Conversación DOP/USD con FAQ real (sin mock FAQ ni continuity)
# ---------------------------------------------------------------------------


def test_inspect_dop_usd_with_real_faq(monkeypatch) -> None:
    import genesis_cognitive.rag.foundry_kb_agent as foundry_mod

    monkeypatch.setattr(foundry_mod, "ask_foundry_kb_agent", lambda *a, **k: None, raising=False)

    snap = _synth_snap("SYN-DOPUSD")
    store = ReactiveSessionStore()
    app = _make_app(store, snap=snap)
    client = TestClient(app)
    conv = "conv-1c-dop-usd"
    _seed(store, conv, snap)

    r1 = _inspect(client, "¿Cuánto tengo disponible?", conv, snap.customer_id)
    assert r1["status"] == "CLARIFICATION_REQUIRED"
    assert "faq" not in _trace_step(r1).lower()
    sess = store.get_session(conv)
    assert sess is not None and sess.pending_action is not None

    r2 = _inspect(client, "La de dólares.", conv, snap.customer_id)
    assert r2["status"] == "VALID_CONTRACT"
    assert "320.50" in (r2["client_response"] or "").replace(",", "")
    assert "USD" in (r2["client_response"] or "")
    step2 = _trace_step(r2)
    assert "pending_continuity" in step2 or "fastpath" in step2 or "continuity" in step2
    sess = store.get_session(conv)
    assert sess is not None
    assert sess.pending_action is None
    assert sess.last_resolved is not None
    assert sess.last_resolved.account_ref == "CA2002USD"

    r3 = _inspect(client, "¿Qué significa saldo disponible?", conv, snap.customer_id)
    # FAQ real puede abstenerse (sin entrada útil) o responder definición relevante
    sess = store.get_session(conv)
    assert sess is not None
    assert sess.last_resolved is not None
    assert sess.last_resolved.account_ref == "CA2002USD"
    if r3["status"] == "VALID_CONTRACT" and r3.get("client_response"):
        low = (r3["client_response"] or "").lower()
        assert "cargo" not in low

    r4 = _inspect(client, "¿Y el disponible de esa cuenta?", conv, snap.customer_id)
    assert r4["status"] == "VALID_CONTRACT"
    assert "faq" not in _trace_step(r4).lower()
    text4 = (r4["client_response"] or "").replace(",", "")
    assert "320.50" in text4 or "320" in text4
    sess = store.get_session(conv)
    assert sess is not None
    assert sess.last_resolved.account_ref == "CA2002USD"

    r5 = _inspect(client, "No, ahora la de pesos.", conv, snap.customer_id)
    assert r5["status"] == "VALID_CONTRACT"
    text5 = (r5["client_response"] or "").replace(",", "")
    # Continuity puede devolver disponible (15000) o saldo libro (15200); producto DOP
    assert "15000" in text5 or "15200" in text5
    assert "DOP" in (r5["client_response"] or "") or "RD$" in (r5["client_response"] or "")
    sess = store.get_session(conv)
    assert sess is not None
    assert sess.last_resolved.account_ref == "CA1001DOP"


# ---------------------------------------------------------------------------
# 4) CAS — bloqueo HTTP E2E, callers, refs mutables (sin declarar /inspect OK)
# ---------------------------------------------------------------------------


def test_cas_http_e2e_commit_uses_expected_revision() -> None:
    """API store exige expected_revision; escritura legacy sin CAS sigue existiendo."""
    store = ReactiveSessionStore()
    snap = _synth_snap("CAS-1C")
    s = SessionState(customer_id=snap.customer_id, snapshot=snap)
    rev = store.put_session("cas-http", s)
    assert rev == 1
    with pytest.raises(SessionConflictError):
        store.put_session(
            "cas-http",
            SessionState(customer_id=snap.customer_id, snapshot=snap, revision=0),
            expected_revision=0,
        )
    # Escritura legacy (contratos externos / tools): sin expected_revision → compatible
    legacy = SessionState(customer_id=snap.customer_id, snapshot=snap, revision=99)
    new_rev = store.put_session("cas-http", legacy)
    assert new_rev == 2
    # /inspect cognitivo ahora usa expected_revision (ver stage1c_close HTTP)


def test_cas_mutable_shared_reference_before_revision_check() -> None:
    """get_session debe devolver copia: mutar no altera el store sin put CAS."""
    store = ReactiveSessionStore()
    snap = _synth_snap("CAS-MUT")
    store.put_session("mut-1", SessionState(customer_id=snap.customer_id, snapshot=snap))
    a = store.get_session("mut-1")
    b = store.get_session("mut-1")
    assert a is not None and b is not None
    assert a is not b
    assert a is not store._sessions["mut-1"]  # noqa: SLF001
    a.history.append({"role": "user", "content": "mutated-before-cas"})
    # Store intacto hasta commit
    assert store.get_session("mut-1").history == []
    assert store._sessions["mut-1"].history == []  # noqa: SLF001


def test_cas_concurrent_one_wins_with_expected_revision() -> None:
    store = ReactiveSessionStore()
    snap = _synth_snap()
    store.put_session("cas-c", SessionState(customer_id=snap.customer_id, snapshot=snap))
    expected = store.get_session("cas-c").revision
    wins: list[str] = []
    errors: list[Exception] = []

    def writer(tag: str) -> None:
        try:
            sess = store.get_session("cas-c")
            assert sess is not None
            # Copia superficial para no compartir mutación entre hilos en el mismo objeto
            clone = SessionState(
                customer_id=sess.customer_id,
                history=list(sess.history) + [{"role": "user", "content": tag}],
                snapshot=sess.snapshot,
                revision=sess.revision,
            )
            store.put_session("cas-c", clone, expected_revision=expected)
            wins.append(tag)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=writer, args=("a",))
    t2 = threading.Thread(target=writer, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(wins) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], SessionConflictError)


# ---------------------------------------------------------------------------
# 5) QA Azure real — harness preparado, NO ejecutar
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "QA Azure real (etapa 1C): requiere autorización remota explícita. "
        "No ejecutar en CI ni en esta entrega. Ver works/QA_AZURE_REAL_1C.md"
    ),
)
def test_qa_azure_real_harness_not_run(monkeypatch) -> None:
    """Plantilla de validación QA — falla si alguien quita el skip por error."""
    required = (
        "GENESIS_QA_AZURE_AUTHORIZED",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT",
    )
    for key in required:
        assert os.getenv(key), f"faltaba {key}"
    assert os.getenv("GENESIS_QA_AZURE_AUTHORIZED") == "1"
    assert os.getenv("GENESIS_AZURE_BRAIN") == "1"
    # Sin Core remoto ni escritura de índice
    assert os.getenv("GENESIS_CORE_URL", "") == ""
    raise AssertionError(
        "Harness QA no debe correrse sin autorización; este assert es red de seguridad"
    )
