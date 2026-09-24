"""Cierre V4 QA — D/E/F/B focalizados (fixtures locales; no acreditan Azure real)."""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from genesis_cognitive.brain.azure_plan_adapter import (
    interpretation_to_turn_plan,
    plan_from_pending_selection,
)
from genesis_cognitive.brain.plan_executor import execute_turn_plan
from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
from genesis_cognitive.brain.turn_plan import PlanTask, TurnPlan
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
from genesis_cognitive.enums import InterpretationMode, SelectedRoute
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


def _loan(pid: str, rate: str) -> LoanSnapshot:
    return LoanSnapshot(
        product_id=pid,
        loan_type="PERSONAL",
        installment_amount=Decimal("0"),
        annual_interest_rate=Decimal(rate),
        outstanding_principal=Decimal("1000"),
        delinquency_days=0,
        next_due_date="2026-10-01",
        payoff_amount=Decimal("1100"),
    )


def _snap_two_loans_one_savings(**kw):
    ledger = kw.get("ledger", Decimal("200"))
    return CustomerContextSnapshot(
        customer_id=kw.get("cid", "SYN"),
        display_name="Lab",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="SAV1", product_type="SAVINGS", alias="Ahorros",
                currency="DOP", status="active",
                available_balance=Decimal("150"),
                ledger_balance=ledger,
            ),
            ProductSnapshot(
                product_id="LN1", product_type="LOAN", alias="Préstamo 1",
                currency="DOP", status="active",
            ),
            ProductSnapshot(
                product_id="LN2", product_type="LOAN", alias="Préstamo 2",
                currency="DOP", status="active",
            ),
        ),
        loans=(_loan("LN1", "12.5"), _loan("LN2", "14.0")),
    )


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


def test_d1_rate_and_definition_two_tasks():
    snap = _snap_two_loans_one_savings()
    plan = interpretation_to_turn_plan(
        _interp(_action(1, "LOAN_DETAIL_READ")),
        "La tasa de mi préstamo y qué significa",
        snapshot=snap,
    )
    assert any(t.object == "glossary" and "interest_rate" in (t.fields or []) for t in plan.tasks)
    loan = next(t for t in plan.tasks if t.object == "loan")
    assert loan.status == "needs_clarification"
    pex = execute_turn_plan(plan, snap, "La tasa de mi préstamo y qué significa")
    assert pex.pending_tasks
    assert any(e.domain == "institutional" for e in pex.evidences)


def test_d2_selection_resumes_pending_rate_and_definition():
    snap = _snap_two_loans_one_savings()
    session = SessionState(customer_id="SYN", snapshot=snap)
    session.pending_tasks = [{
        "task_id": "t2",
        "object": "loan",
        "fields": ["rate"],
        "original_question": "La tasa de mi préstamo y qué significa",
        "display_order": ["LN1", "LN2"],
    }]
    plan = plan_from_pending_selection(
        selected_ref="LN1", session=session, question="LN1",
    )
    assert plan is not None
    assert any(t.object == "loan" and t.entity_ref == "LN1" for t in plan.tasks)
    assert any(t.object == "glossary" for t in plan.tasks)
    pex = execute_turn_plan(plan, snap, "LN1", session=session)
    assert "12.5" in (pex.text or "")


def test_f1_account_and_loan_two_tasks():
    snap = _snap_two_loans_one_savings()
    plan = interpretation_to_turn_plan(
        _interp(
            _action(1, "ACCOUNT_BALANCE_READ", account_ref="SAV1"),
            _action(2, "LOAN_DETAIL_READ"),
        ),
        "Dime el disponible de mi cuenta y la tasa de mi préstamo",
        snapshot=snap,
    )
    assert len(plan.tasks) >= 2
    pex = execute_turn_plan(
        plan, snap, "Dime el disponible de mi cuenta y la tasa de mi préstamo",
    )
    assert pex.pending_tasks
    assert any("150" in (e.text or "") or "disponible" in (e.text or "").lower() for e in pex.evidences)


def test_f2_selection_completes_loan_rate():
    snap = _snap_two_loans_one_savings()
    session = SessionState(customer_id="SYN", snapshot=snap)
    session.pending_tasks = [{
        "task_id": "t2",
        "object": "loan",
        "fields": ["rate"],
        "original_question": "disponible de mi cuenta y la tasa de mi préstamo",
        "display_order": ["LN1", "LN2"],
    }]
    plan = plan_from_pending_selection(selected_ref="LN2", session=session, question="LN2")
    pex = execute_turn_plan(plan, snap, "LN2", session=session)
    assert "14" in (pex.text or "")


def test_e1_correction_plus_mission_one_checking():
    snap = CustomerContextSnapshot(
        customer_id="E1", display_name="Lab", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="CHK1", product_type="CHECKING", alias="Corriente",
                currency="DOP", status="active",
                available_balance=Decimal("80"), ledger_balance=Decimal("90"),
            ),
            ProductSnapshot(
                product_id="SAV1", product_type="SAVINGS", alias="Ahorros",
                currency="DOP", status="active",
                available_balance=Decimal("10"), ledger_balance=Decimal("11"),
            ),
        ),
        loans=(),
    )
    plan = interpretation_to_turn_plan(
        _interp(
            _action(1, "ACCOUNT_BALANCE_READ"),
            _action(2, "BUSINESS_KNOWLEDGE_QUERY", knowledge_topic="mision"),
        ),
        "No, la corriente; además dime la misión",
        snapshot=snap,
        session=SessionState(customer_id="E1"),
    )
    assert plan.transition == "correction"
    assert any(t.object == "account" and t.entity_ref == "CHK1" for t in plan.tasks)
    assert any(t.domain == "institutional" and "mision" in (t.fields or []) for t in plan.tasks)
    pex = execute_turn_plan(plan, snap, "No, la corriente; además dime la misión")
    assert pex.status != "PROVIDER_ERROR"
    assert len(pex.text or "") > 20


def test_e2_no_checking_absent_plus_mission():
    snap = _snap_two_loans_one_savings()
    plan = interpret_turn_plan(
        "No, la corriente; dime la misión",
        SessionState(customer_id="E2", snapshot=snap),
        snapshot=snap,
    )
    assert plan.transition == "correction"
    pex = execute_turn_plan(plan, snap, "No, la corriente; dime la misión")
    assert any(e.status == "absent" and e.domain == "personal" for e in pex.evidences)
    assert any(e.domain == "institutional" for e in pex.evidences)


def test_e3_two_checking_clarify_plus_mission():
    snap = CustomerContextSnapshot(
        customer_id="E3", display_name="Lab", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="C1", product_type="CHECKING", alias="Corriente 1",
                currency="DOP", status="active", available_balance=Decimal("1"), ledger_balance=Decimal("1"),
            ),
            ProductSnapshot(
                product_id="C2", product_type="CHECKING", alias="Corriente 2",
                currency="DOP", status="active", available_balance=Decimal("2"), ledger_balance=Decimal("2"),
            ),
        ),
        loans=(),
    )
    plan = interpret_turn_plan(
        "No, la corriente; además la misión",
        SessionState(customer_id="E3"),
        snapshot=snap,
    )
    pex = execute_turn_plan(plan, snap, "No, la corriente; además la misión")
    assert any(e.status == "needs_clarification" for e in pex.evidences)
    assert any(e.domain == "institutional" for e in pex.evidences)


def test_b1_available_vs_ledger_distinct():
    snap = _snap_two_loans_one_savings(ledger=Decimal("200"))
    plan_av = TurnPlan(tasks=[PlanTask(
        id="t1", domain="personal", action="read_field", object="account",
        fields=["available"], entity_ref="SAV1", status="ready",
    )])
    plan_ld = TurnPlan(tasks=[PlanTask(
        id="t1", domain="personal", action="read_field", object="account",
        fields=["balance"], entity_ref="SAV1", status="ready",
    )])
    a = execute_turn_plan(plan_av, snap, "disponible")
    b = execute_turn_plan(plan_ld, snap, "saldo contable")
    assert "150" in a.text
    assert "200" in b.text
    assert a.text != b.text


def test_b2_ledger_null_not_substituted():
    products = (
        ProductSnapshot(
            product_id="SAV1", product_type="SAVINGS", alias="Ahorros",
            currency="DOP", status="active",
            available_balance=Decimal("150"), ledger_balance=None,
        ),
    )
    snap = CustomerContextSnapshot(
        customer_id="B2", display_name="Lab", default_currency="DOP",
        products=products, loans=(),
    )
    plan = TurnPlan(tasks=[PlanTask(
        id="t1", domain="personal", action="read_field", object="account",
        fields=["balance"], entity_ref="SAV1", status="ready",
    )])
    pex = execute_turn_plan(plan, snap, "saldo contable")
    assert "150" not in pex.text
    assert "ausente" in pex.text.lower() or "no está disponible" in pex.text.lower()


def test_b3_ledger_zero_preserved():
    products = (
        ProductSnapshot(
            product_id="SAV1", product_type="SAVINGS", alias="Ahorros",
            currency="DOP", status="active",
            available_balance=Decimal("150"), ledger_balance=Decimal("0"),
        ),
    )
    snap = CustomerContextSnapshot(
        customer_id="B3", display_name="Lab", default_currency="DOP",
        products=products, loans=(),
    )
    plan = TurnPlan(tasks=[PlanTask(
        id="t1", domain="personal", action="read_field", object="account",
        fields=["balance"], entity_ref="SAV1", status="ready",
    )])
    pex = execute_turn_plan(plan, snap, "saldo contable")
    assert "ausente" not in pex.text.lower()
    assert "0" in pex.text or "RD$" in pex.text


def test_p2_paraphrase_without_y_ademas():
    snap = _snap_two_loans_one_savings()
    plan2 = interpretation_to_turn_plan(
        _interp(_action(1, "ACCOUNT_BALANCE_READ")),
        "Me refería a la corriente. Incluye la misión",
        snapshot=snap,
    )
    assert any(t.domain == "institutional" for t in plan2.tasks)


def test_d_selection_resolves_apk_option_ref():
    from genesis_cognitive.brain.azure_plan_adapter import (
        is_unequivocal_structured_shortcut,
        plan_from_pending_selection,
    )
    from genesis_cognitive.context.app_channel import build_option_ref

    snap = _snap_two_loans_one_savings()
    loan = next(p for p in snap.products if p.product_id == "LN1")
    ref = build_option_ref(loan)
    sess = SessionState(
        customer_id="SYN",
        snapshot=snap,
        pending_tasks=[{
            "task_id": "t2",
            "object": "loan",
            "fields": ["rate"],
            "original_question": "La tasa de mi préstamo y qué significa",
            "display_order": ["LN1", "LN2"],
        }],
    )
    ok, reason = is_unequivocal_structured_shortcut(ref, sess, snapshot=snap)
    assert ok and reason == "structured_product_ref"
    plan = plan_from_pending_selection(
        selected_ref=ref, session=sess, question=ref, snapshot=snap,
    )
    assert plan is not None
    assert plan.transition == "continue"
    assert any(t.entity_ref == "LN1" and t.object == "loan" for t in plan.tasks)


def test_f1_tasa_y_saldo_two_tasks():
    snap = _snap_two_loans_one_savings()
    plan = interpret_turn_plan(
        "Quiero la tasa de mi préstamo y también el saldo de mi cuenta",
        SessionState(customer_id="SYN", snapshot=snap),
        snapshot=snap,
    )
    assert len(plan.tasks) >= 2
    assert any(t.object == "loan" and "rate" in (t.fields or []) for t in plan.tasks)
    assert any(t.object == "account" for t in plan.tasks)


@pytest.mark.asyncio
async def test_none_interpretation_triggers_structural_repair():
    """CLARIFICATION/NON_OPERATIONAL con interpretation=None no debe AttributeError."""
    from genesis_cognitive.brain.azure_plan_turn import run_azure_plan_path

    snap = _snap_two_loans_one_savings()
    sess = SessionState(customer_id="SYN", snapshot=snap)
    resolver = MagicMock()
    result = MagicMock()
    result.status = "CLARIFICATION_REQUIRED"
    result.interpretation = None
    result.non_operational_message = None
    result.call_records = [MagicMock(name="proposer", duration_ms=10, deployment="t")]
    # MagicMock name= shadows; set attrs explicitly
    rec = MagicMock()
    rec.name = "proposer"
    rec.duration_ms = 10
    rec.deployment = "t"
    result.call_records = [rec]
    resolver.resolve_full = AsyncMock(return_value=result)

    from genesis_cognitive.context.adapters.in_memory_capability_context import InMemoryCapabilityContextProvider
    from genesis_cognitive.context.adapters.in_memory_conversation_context import InMemoryConversationContextProvider
    from genesis_cognitive.context.adapters.in_memory_pending_operation_context import InMemoryPendingOperationContextProvider
    from genesis_cognitive.context.adapters.in_memory_portfolio_context import InMemoryPortfolioContextProvider
    from genesis_cognitive.context.context_assembler import ContextAssembler
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.model_input.model_input_builder import ModelInputBuilder
    from genesis_cognitive.validation.input_validator import InputValidator

    out = await run_azure_plan_path(
        question="La tasa de mi préstamo y qué significa",
        safe_question="La tasa de mi préstamo y qué significa",
        session_state=sess,
        history=[],
        customer_snapshot=snap,
        resolver=resolver,
        model_input_builder=ModelInputBuilder(),
        context_assembler=ContextAssembler(
            InMemoryConversationContextProvider(),
            InMemoryPortfolioContextProvider(data={}),
            InMemoryPendingOperationContextProvider(),
            InMemoryCapabilityContextProvider(CapabilityCatalog()),
        ),
        input_validator=InputValidator(),
        conv_id="c-none-interp",
        customer_id="SYN",
        turn_number=1,
        azure_model="test",
        prompt_version="test",
        request_start=time.perf_counter(),
    )
    assert out["status"] != "PROVIDER_ERROR"
    assert out.get("_plan") is not None
    assert len(out["_plan"].tasks) >= 1
    trace = (out.get("decision_trace") or [{}])[0].get("output") or {}
    assert trace.get("brain_source") == "structural_repair"
    assert "SEMANTIC_AZURE_PLAN_FAILED" != out.get("intent_id")


def test_azure_plan_no_fallthrough_to_fastpath(monkeypatch: pytest.MonkeyPatch):
    from genesis_cognitive.context.adapters.in_memory_capability_context import InMemoryCapabilityContextProvider
    from genesis_cognitive.context.adapters.in_memory_conversation_context import InMemoryConversationContextProvider
    from genesis_cognitive.context.adapters.in_memory_pending_operation_context import InMemoryPendingOperationContextProvider
    from genesis_cognitive.context.adapters.in_memory_portfolio_context import InMemoryPortfolioContextProvider
    from genesis_cognitive.context.context_assembler import ContextAssembler
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
    from genesis_cognitive.demo.contract_inspector_app import create_app
    from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError
    from genesis_cognitive.model_input.model_input_builder import ModelInputBuilder
    from genesis_cognitive.validation.input_validator import InputValidator

    snap = _snap_two_loans_one_savings()
    store = ReactiveSessionStore()
    store.put_snapshot("SYN", snap, mark_fetched_now=True)
    store.put_session("c-fail", SessionState(customer_id="SYN", snapshot=snap, snapshot_source_fetched_at=time.time()))

    resolver = MagicMock()
    resolver.resolve_full = AsyncMock(side_effect=InvalidModelOutputError())
    app = create_app(
        resolver=resolver,
        gate=SemanticContractGate(),
        input_validator=InputValidator(),
        context_assembler=ContextAssembler(
            InMemoryConversationContextProvider(),
            InMemoryPortfolioContextProvider(data={}),
            InMemoryPendingOperationContextProvider(),
            InMemoryCapabilityContextProvider(CapabilityCatalog()),
        ),
        model_input_builder=ModelInputBuilder(),
        azure_model="test",
        prompt_version="test",
        db_path=None,
        session_store=store,
    )
    client = TestClient(app)
    r = client.post("/turn", json={
        "question": "La tasa de mi préstamo y qué significa",
        "conversation_id": "c-fail",
        "customer_id": "SYN",
    })
    assert r.status_code == 200
    body = r.json()
    audit = body.get("audit") or {}
    trace = str(audit.get("decision_trace") or body.get("decision_trace") or "")
    status = (body.get("app_channel") or {}).get("status") or body.get("status")
    assert "field_fastpath" not in trace
    assert "azure_plan" in trace
    route = ""
    if isinstance(audit.get("decision_trace"), list) and audit["decision_trace"]:
        route = str((audit["decision_trace"][0].get("output") or {}).get("route_source") or "")
    assert (
        status == "PROVIDER_ERROR"
        or "repair:" in route
        or "repair:" in trace
    )


def test_mi_tasa_uses_all_rate_bearing_products_not_only_loans() -> None:
    from genesis_cognitive.brain.azure_plan_adapter import _supplement_tasks_from_question

    snap = CustomerContextSnapshot(
        customer_id="SYN",
        display_name="Lab",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="LN1", product_type="LOAN", alias="Préstamo 1",
                currency="DOP", status="active",
            ),
            ProductSnapshot(
                product_id="DAP1", product_type="TERM_DEPOSIT", alias="Certificado",
                currency="DOP", status="active", interest_rate=Decimal("8.1"),
                maturity_date="2026-12-01",
            ),
            ProductSnapshot(
                product_id="TC_JOVEN", product_type="CREDIT_CARD", alias="Tarjeta Joven",
                currency="DOP", status="active", interest_rate=Decimal("42.5"),
                ledger_balance=Decimal("100"),
            ),
        ),
        loans=(_loan("LN1", "12.5"),),
    )
    loan_only = [
        PlanTask(
            id="t1", domain="personal", action="read_field", object="loan",
            fields=["rate"], status="needs_clarification",
            unresolved_slots=["entity_ref"],
        )
    ]
    fixed = _supplement_tasks_from_question(
        loan_only, "cuál es mi tasa de interés", snapshot=snap,
    )
    rate_tasks = [t for t in fixed if t.domain == "personal" and "rate" in (t.fields or [])]
    assert len(rate_tasks) == 1
    ids = (rate_tasks[0].filters or {}).get("candidate_ids") or []
    assert set(ids) == {"LN1", "DAP1", "TC_JOVEN"}
    assert rate_tasks[0].object == "product"

    plan = interpret_turn_plan("cuál es el saldo de mi tarjeta joven", None, snapshot=snap)
    assert plan.tasks
    assert plan.tasks[0].object == "credit_card"
    assert plan.tasks[0].entity_ref == "TC_JOVEN"
    assert plan.tasks[0].fields == ["balance"]

    plan_rate = interpret_turn_plan("cuál es la tasa de mi tarjeta joven", None, snapshot=snap)
    assert plan_rate.tasks[0].entity_ref == "TC_JOVEN"
    assert plan_rate.tasks[0].fields == ["rate"]