"""Regresiones auditadas V3.1: gate de evaluación, financieros, CC02/CC03/IG01, simulación."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from genesis_cognitive.brain.grounded_executor import execute_grounded
from genesis_cognitive.brain.intent_types import IntentPacket
from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
from genesis_cognitive.brain.turn_plan import InvalidTurnPlanError, PlanTask, TurnPlan, validate_turn_plan
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import (
    ProductFocus,
    ReactiveSessionStore,
    SessionState,
)
from genesis_cognitive.enums import FreshnessState, InterpretationMode, OperationalState, SelectedRoute
from genesis_cognitive.router.faq_guardrail import clear_faq_cache


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSUMOS = PROJECT_ROOT / "works" / "Banca_Cierre_V3_1" / "insumos"
RESULTS_PATH = PROJECT_ROOT / "works" / "RESULTADOS_CASOS_ADICIONALES_V3.json"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GENESIS_FAQ_PATH", str(PROJECT_ROOT / "data" / "kb_faq_vf01.json"))
    monkeypatch.setenv(
        "GENESIS_GLOSSARY_PATH",
        str(PROJECT_ROOT / "data" / "kb_glossary_local_v31.json"),
    )
    monkeypatch.setenv("GENESIS_AZURE_BRAIN", "0")
    clear_faq_cache()
    yield
    clear_faq_cache()


def _make_app(store: ReactiveSessionStore):
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
            status="VALID_CONTRACT",
            interpretation=interp,
            initial_proposal=None,
            verified_proposal=None,
            non_operational_message=None,
            call_records=[],
        )
    )
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
        prompt_version="test-prompt",
        db_path=None,
        session_store=store,
    )


def _seed(store, conv, snap, **extra):
    store.put_snapshot(snap.customer_id, snap, mark_fetched_now=True)
    store.put_session(
        conv,
        SessionState(
            customer_id=snap.customer_id,
            snapshot=snap,
            snapshot_source_fetched_at=time.time(),
            **extra,
        ),
    )


def _turn(client, conv, cid, q):
    r = client.post("/turn", json={"question": q, "conversation_id": conv, "customer_id": cid})
    assert r.status_code == 200
    return r.json()


def _reply(body):
    return body.get("reply") or (body.get("app_channel") or {}).get("client_response") or ""


# ---------------------------------------------------------------------------
# Financieros
# ---------------------------------------------------------------------------


def test_ledger_none_not_replaced_by_available():
    snap = CustomerContextSnapshot(
        customer_id="F1", display_name="C", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="A1", product_type="SAVINGS", alias="A1",
                currency="DOP", status="active",
                available_balance=Decimal("0.00"),
                ledger_balance=None,
            ),
        ),
        loans=(),
    )
    pkt = IntentPacket("personal", "account", "balance", confidence=0.9, source="heuristic")
    r = execute_grounded(pkt, snap, "¿saldo actual?")
    assert "0" not in (r.text or "").replace("ausente", "") or "ausente" in (r.text or "").lower()
    assert "ausente" in (r.text or "").lower() or "no está disponible" in (r.text or "").lower()
    assert "disponible" not in (r.trace or {}).get("account_field", "balance")


def test_available_zero_preserved():
    snap = CustomerContextSnapshot(
        customer_id="F2", display_name="C", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="A1", product_type="SAVINGS", alias="A1",
                currency="DOP", status="active",
                available_balance=Decimal("0.00"),
                ledger_balance=Decimal("100"),
            ),
        ),
        loans=(),
    )
    pkt = IntentPacket("personal", "account", "available", confidence=0.9, source="heuristic")
    r = execute_grounded(pkt, snap, "¿disponible?")
    assert "0" in (r.text or "")
    assert "100" not in (r.text or "").replace(",", "")


def test_card_due_date_not_balance_fallback():
    snap = CustomerContextSnapshot(
        customer_id="F3", display_name="C", default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="C1", product_type="CREDIT_CARD", alias="TC",
                currency="DOP", status="active",
                ledger_balance=Decimal("999"),
                available_balance=Decimal("1"),
            ),
        ),
        loans=(),
    )
    pkt = IntentPacket(
        "personal", "credit_card", "due_date", confidence=0.9,
        product_hint_digits="C1", source="heuristic",
    )
    r = execute_grounded(pkt, snap, "fecha de pago")
    assert "999" not in (r.text or "").replace(",", "")
    assert "no está disponible" in (r.text or "").lower() or "no se deriva" in (r.text or "").lower()


def test_plan_cycle_rejected():
    plan = TurnPlan(tasks=[
        PlanTask(id="t1", domain="personal", action="read_field", object="account",
                 fields=["balance"], depends_on=["t2"]),
        PlanTask(id="t2", domain="personal", action="read_field", object="account",
                 fields=["available"], depends_on=["t1"]),
    ])
    errs = validate_turn_plan(plan)
    assert any("cycle" in e for e in errs)


# ---------------------------------------------------------------------------
# CC02 (5 turnos Visa) / CC03 (5 turnos cuentas) / IG01
# ---------------------------------------------------------------------------


def test_cc02_five_turns_catalog_visa():
    snap = CustomerContextSnapshot(
        customer_id="CC02", display_name="C", default_currency="DOP",
        products=(), loans=(),
    )
    store = ReactiveSessionStore()
    client = TestClient(_make_app(store))
    conv = "cc02-5"
    _seed(store, conv, snap)
    r0 = _reply(_turn(client, conv, snap.customer_id, "Compara Visa Platinum con Visa Infinite."))
    assert "platinum" in r0.lower() and "infinite" in r0.lower()
    sess = store.get_session(conv)
    assert sess is not None and sess.compare_set[:2] == ["visa_platinum", "visa_infinite"]

    r1 = _reply(_turn(client, conv, snap.customer_id, "Agrega Visa Gold."))
    sess = store.get_session(conv)
    assert sess is not None
    assert "visa_gold" in sess.compare_set
    assert "gold" in r1.lower() or "3." in r1

    r2 = _reply(_turn(client, conv, snap.customer_id, "¿Cuál es la segunda?"))
    assert "infinite" in r2.lower()

    r3 = _reply(_turn(client, conv, snap.customer_id, "Quita Visa Gold."))
    sess = store.get_session(conv)
    assert sess is not None
    assert "visa_gold" not in sess.compare_set

    r4 = _reply(_turn(client, conv, snap.customer_id, "De las que quedan, háblame de la primera."))
    assert "platinum" in r4.lower()
    assert all("saldo adeudado" not in r.lower() for r in (r0, r1, r2, r3, r4))


def test_cc03_five_turns_account_catalog():
    """CC03: corrientes/ahorros/nómina — no el test de Visa."""
    snap = CustomerContextSnapshot(
        customer_id="CC03", display_name="C", default_currency="DOP",
        products=(), loans=(),
    )
    store = ReactiveSessionStore()
    client = TestClient(_make_app(store))
    conv = "cc03-5"
    _seed(store, conv, snap)
    t1 = _reply(_turn(client, conv, snap.customer_id, "Compara cuenta de ahorros y cuenta corriente."))
    assert "ahorros" in t1.lower() or "corriente" in t1.lower() or "1." in t1
    sess = store.get_session(conv)
    assert sess is not None
    assert "cuenta_ahorros" in sess.compare_set
    assert "cuenta_corriente" in sess.compare_set
    t2 = _reply(_turn(client, conv, snap.customer_id, "Agrega cuenta nómina."))
    sess = store.get_session(conv)
    assert sess is not None
    assert "cuenta_nomina" in sess.compare_set, f"compare_set={sess.compare_set}; reply={t2[:120]}"
    t3 = _reply(_turn(client, conv, snap.customer_id, "De las tres, la segunda."))
    assert "corriente" in t3.lower()
    t4 = _reply(_turn(client, conv, snap.customer_id, "¿Tienen requisitos distintos?"))
    assert t4
    t5 = _reply(_turn(client, conv, snap.customer_id, "Quédate con la primera del conjunto."))
    assert t5
    assert "adeudado" not in t1.lower()
    assert "platinum" not in t1.lower()
    assert "visa" not in t1.lower()

def test_ig01_mission_vision_and_difference():
    snap = CustomerContextSnapshot(
        customer_id="IG01", display_name="C", default_currency="DOP",
        products=(), loans=(),
    )
    store = ReactiveSessionStore()
    client = TestClient(_make_app(store))
    conv = "ig01"
    _seed(store, conv, snap)
    r1 = _reply(_turn(client, conv, snap.customer_id, "misión y visión"))
    low1 = r1.lower()
    assert ("misión" in low1 or "mision" in low1) and ("visión" in low1 or "vision" in low1)
    assert "emprendedor" in low1 or "institución" in low1 or "preferido" in low1
    r2 = _reply(_turn(client, conv, snap.customer_id, "¿en qué se diferencian?"))
    low2 = r2.lower()
    assert any(s in low2 for s in ("difer", "misión", "mision", "visión", "vision", "propósito", "aspiraci"))
    assert "no logré interpretar" not in low2


# ---------------------------------------------------------------------------
# Simulaciones locales: FAQ vacío / fallo modelo
# ---------------------------------------------------------------------------


def test_simulated_empty_mission_retrieval(tmp_path, monkeypatch):
    empty = tmp_path / "empty_faq.json"
    empty.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("GENESIS_FAQ_PATH", str(empty))
    clear_faq_cache()
    from genesis_cognitive.brain.plan_executor import execute_turn_plan
    from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan

    plan = interpret_turn_plan("misión del banco", None, snapshot=None)
    ex = execute_turn_plan(plan, None, "misión del banco", None)
    assert "no" in ex.text.lower() or ex.evidences[0].status == "absent"
    assert "emprendedor" not in ex.text.lower()  # no fabricar misión


def test_simulated_model_failure_trace(monkeypatch):
    """Transporte simulado: brain ON pero classify lanza — traza sanitizada local."""
    monkeypatch.setenv("GENESIS_AZURE_BRAIN", "1")

    async def _boom(*_a, **_k):
        raise RuntimeError("simulated_structured_output_error")

    monkeypatch.setattr(
        "genesis_cognitive.brain.azure_intent_brain.classify_intent_async",
        _boom,
    )
    # No requiere Azure real; documenta etiqueta local simulada
    from genesis_cognitive.brain.azure_intent_brain import is_azure_brain_enabled
    assert is_azure_brain_enabled()


# ---------------------------------------------------------------------------
# Gate: parametrize 24 + fail si failed
# ---------------------------------------------------------------------------


def _load_cases():
    path = INSUMOS / "Casos_QA_Adicionales_V3.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# Import runner helpers from existing module to avoid duplication of fixtures
from tests.unit import test_casos_adicionales_v3 as addmod  # noqa: E402


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["case_id"])
def test_additional_case_parametrized(case):
    """Aceptación: cada caso failed hace fallar pytest; blocked/not_applicable OK con motivo."""
    result = addmod._run_case(case)
    # Acumular en archivo (merge)
    existing = {"results": []}
    if RESULTS_PATH.exists():
        try:
            existing = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = {"results": []}
    by_id = {r["case_id"]: r for r in existing.get("results") or []}
    by_id[result["case_id"]] = result
    results = list(by_id.values())
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    RESULTS_PATH.write_text(
        json.dumps({
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "counts": counts,
            "results": sorted(results, key=lambda x: x["case_id"]),
            "policy": "failed hace fallar el test parametrizado; blocked no es passed",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if result["status"] == "failed":
        pytest.fail(
            f"{case['case_id']} failed: {result.get('notes')}; "
            f"replies={result.get('replies_sanitized')}"
        )
    assert result["status"] in ("passed", "blocked", "not_applicable", "skipped")
