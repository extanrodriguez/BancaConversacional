"""Estabilización cognitiva etapa 1: schema, continuidad, frescura y multi-turno.

Pruebas locales con mocks/sintéticos. NO validan el modelo Azure real.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

import pytest

from genesis_cognitive.brain.azure_intent_brain import (
    BrainInterpretationError,
    _BRAIN_SCHEMA,
    _session_summary,
    heuristic_intent,
    validate_brain_payload,
)
from genesis_cognitive.brain.continuity import resolve_product_reference
from genesis_cognitive.brain.grounded_executor import execute_grounded
from genesis_cognitive.brain.intent_types import IntentPacket
from genesis_cognitive.brain.turn_orchestrator import run_azure_brain_turn
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.query_spec import build_query_spec
from genesis_cognitive.context.reactive_store import (
    LastResolved,
    PendingAction,
    ReactiveSessionStore,
    SessionState,
    SnapshotEntry,
)
from genesis_cognitive.context.redis_session_store import session_from_dict, session_to_dict
from genesis_cognitive.router.product_focus import remember_product_focus


def _snap(
    *,
    dop_available: str = "15000.00",
    dop_ledger: str = "15200.00",
    usd_available: str = "320.50",
    usd_ledger: str = "350.00",
    customer_id: str = "CLI-DUP",
    name: str = "Ana Dual",
) -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id=customer_id,
        display_name=name,
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="CA1001DOP",
                product_type="SAVINGS",
                alias="Ahorros pesos",
                currency="DOP",
                status="active",
                available_balance=Decimal(dop_available),
                ledger_balance=Decimal(dop_ledger),
                last_four="1001",
            ),
            ProductSnapshot(
                product_id="CA2002USD",
                product_type="SAVINGS",
                alias="Ahorros dólares",
                currency="USD",
                status="active",
                available_balance=Decimal(usd_available),
                ledger_balance=Decimal(usd_ledger),
                last_four="2002",
            ),
        ),
        loans=(),
    )


def _apply_result_to_session(session: SessionState, question: str, result) -> None:
    from genesis_cognitive.router.product_focus import (
        remember_product_focus as remember,
        should_update_last_resolved,
    )

    session.history.append({"role": "user", "content": question})
    if result is None:
        return
    if result.status == "CLARIFICATION_REQUIRED":
        session.pending_action = PendingAction(
            intent_id=result.intent_id or "CLARIFICATION",
            capability_candidate="PRODUCT_FIELD",
            selected_route="PERSONAL_READ",
            detected_entities={"account_ref": None},
            missing_requirements=(
                (result.actions[0].get("missing_requirements") if result.actions else None)
                or ["account_ref"]
            ),
            suggested_question=result.text or "",
            original_question=question,
            query_spec=build_query_spec(question, result.intent_id),
        )
    else:
        session.pending_action = None
        if should_update_last_resolved(
            result.intent_id, result.account_ref, session, question,
        ):
            session.last_resolved = LastResolved(
                intent_id=result.intent_id or "",
                account_ref=result.account_ref or "",
                original_question=question,
            )
            remember(session, result.intent_id, result.account_ref, question)
        if result.route == "knowledge" or result.intent_id == "BUSINESS_KNOWLEDGE_QUERY":
            session.last_knowledge_topic = "disponible"
    session.history.append({"role": "assistant", "content": (result.text or "")[:200]})


async def _turn(question: str, snap: CustomerContextSnapshot, session: SessionState):
    result = await run_azure_brain_turn(question, snap, session=session)
    _apply_result_to_session(session, question, result)
    return result


def test_brain_schema_strict_compatible() -> None:
    props = set(_BRAIN_SCHEMA["properties"])
    required = set(_BRAIN_SCHEMA["required"])
    assert props == required
    assert _BRAIN_SCHEMA["additionalProperties"] is False
    for key in (
        "clarification_question",
        "product_hint_digits",
        "rewritten_question",
        "rationale",
    ):
        assert _BRAIN_SCHEMA["properties"][key]["type"] == ["string", "null"]


def test_validate_brain_payload_accepts_nullables() -> None:
    payload = {
        "family": "personal",
        "product": "account",
        "field": "available",
        "scope": "single",
        "confidence": 0.9,
        "needs_clarification": False,
        "clarification_question": None,
        "product_hint_digits": None,
        "rewritten_question": None,
        "rationale": None,
    }
    validated = validate_brain_payload(payload)
    assert validated["field"] == "available"


def test_validate_brain_payload_rejects_missing_and_extra() -> None:
    with pytest.raises(BrainInterpretationError) as missing:
        validate_brain_payload({"family": "personal"})
    assert missing.value.kind == "schema_violation"
    good = {
        "family": "personal",
        "product": "account",
        "field": "balance",
        "scope": "single",
        "confidence": 0.5,
        "needs_clarification": False,
        "clarification_question": None,
        "product_hint_digits": None,
        "rewritten_question": None,
        "rationale": None,
        "extra_field": "nope",
    }
    with pytest.raises(BrainInterpretationError) as extra:
        validate_brain_payload(good)
    assert "extra" in extra.value.detail


def test_session_summary_includes_pending_and_turns() -> None:
    snap = _snap()
    session = SessionState(
        customer_id="CLI-DUP",
        pending_action=PendingAction(
            intent_id="ACCOUNT_BALANCE_READ",
            capability_candidate="ACCOUNT_BALANCE",
            selected_route="PERSONAL_READ",
            detected_entities={"account_ref": None},
            missing_requirements=["account_ref"],
            suggested_question="¿Cuál cuenta?",
            original_question="¿Cuánto tengo disponible?",
            query_spec={"field": "available_balance", "scope": "single"},
        ),
        last_resolved=LastResolved(
            intent_id="ACCOUNT_BALANCE_READ",
            account_ref="CA2002USD",
            original_question="disponible",
        ),
        history=[
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "¿en qué ayudo?"},
        ],
        last_knowledge_topic="disponible",
    )
    summary = _session_summary(session, snap)
    assert "pending=" in summary
    assert "available_balance" in summary
    assert "last_resolved=" in summary
    assert "kb_topic=disponible" in summary
    assert "turns=" in summary
    assert "CA2002USD" not in summary


def test_put_session_does_not_refresh_source_fetched_at() -> None:
    store = ReactiveSessionStore()
    snap = _snap()
    store.put_snapshot("CLI-DUP", snap, mark_fetched_now=True)
    age1 = store.get_snapshot_age("CLI-DUP")
    assert age1 is not None and age1 < 2
    time.sleep(0.05)
    session = SessionState(customer_id="CLI-DUP", snapshot=snap)
    store.put_session("conv-1", session)
    store.put_session("conv-1", session)
    age2 = store.get_snapshot_age("CLI-DUP")
    assert age2 is not None
    assert age2 >= age1


def test_legacy_snapshot_without_source_fetched_at_is_unknown() -> None:
    store = ReactiveSessionStore()
    snap = _snap()
    with store._snapshot_lock:
        store._snapshots["OLD"] = SnapshotEntry(
            snapshot=snap,
            loaded_at=time.time(),
            source_fetched_at=None,
        )
    assert store.get_snapshot_age("OLD") is None


def test_stale_snapshot_age_visible_when_ttl_configured() -> None:
    store = ReactiveSessionStore(snapshot_ttl_s=1.0)
    snap = _snap()
    store.put_snapshot("CLI-DUP", snap, source_fetched_at=time.time() - 5)
    assert store.get_snapshot_age("CLI-DUP") is None


def test_two_clients_isolated_sessions() -> None:
    store = ReactiveSessionStore()
    a = SessionState(customer_id="A", snapshot=_snap(customer_id="A", name="A"))
    b = SessionState(customer_id="B", snapshot=_snap(customer_id="B", name="B"))
    a.pending_action = PendingAction(
        intent_id="ACCOUNT_BALANCE_READ",
        capability_candidate="X",
        selected_route="PERSONAL_READ",
        detected_entities={},
        missing_requirements=["account_ref"],
        suggested_question="?",
        original_question="saldo",
    )
    store.put_session("conv-a", a)
    store.put_session("conv-b", b)
    assert store.get_session("conv-a").pending_action is not None
    assert store.get_session("conv-b").pending_action is None


def test_external_session_contract_roundtrip() -> None:
    session = SessionState(
        customer_id="CLI-DUP",
        pending_action=PendingAction(
            intent_id="ACCOUNT_BALANCE_READ",
            capability_candidate="ACCOUNT_BALANCE",
            selected_route="PERSONAL_READ",
            detected_entities={"account_ref": None},
            missing_requirements=["account_ref"],
            suggested_question="¿Cuál?",
            original_question="disponible",
            query_spec={"field": "available_balance"},
        ),
    )
    restored = session_from_dict(session_to_dict(session))
    assert restored.pending_action is not None
    assert restored.pending_action.query_spec["field"] == "available_balance"


def test_acceptance_dual_currency_conversation(monkeypatch) -> None:
    """Aceptación multi-turno con clasificador heurístico mockeado (no Azure real)."""
    monkeypatch.setenv("GENESIS_AZURE_BRAIN", "1")

    async def fake_draft(_q, text, **_kwargs):
        return text

    async def fake_classify(question, *, snapshot=None, session=None):
        return heuristic_intent(question, session)

    from genesis_cognitive.brain import turn_orchestrator
    import genesis_cognitive.router.faq_guardrail as faq_mod

    monkeypatch.setattr(turn_orchestrator, "draft_natural_async", fake_draft)
    monkeypatch.setattr(turn_orchestrator, "classify_intent_async", fake_classify)

    def fake_faq(snapshot, question, session=None):
        return (
            "VALID_CONTRACT",
            [{
                "sequence": 1,
                "intent_id": "BUSINESS_KNOWLEDGE_QUERY",
                "detected_entities": {"knowledge_topic": "disponible"},
                "confidence": 0.95,
            }],
            f"{snapshot.display_name}, el disponible es el monto que puedes usar ahora.",
            None,
        )

    monkeypatch.setattr(faq_mod, "apply_faq_guardrail", fake_faq)

    snap = _snap()
    session = SessionState(customer_id="CLI-DUP", snapshot=snap)

    r1 = asyncio.run(_turn("¿Cuánto tengo disponible?", snap, session))
    assert r1 is not None
    assert r1.status == "CLARIFICATION_REQUIRED"
    assert session.pending_action is not None
    assert session.pending_action.query_spec.get("field") == "available_balance"

    r2 = asyncio.run(_turn("La de dólares", snap, session))
    assert r2 is not None
    assert r2.status == "VALID_CONTRACT"
    assert r2.account_ref == "CA2002USD"
    text2 = (r2.text or "").replace(",", "")
    assert "320.50" in text2 or "32050" in text2.replace(".", "")
    assert "USD" in (r2.text or "")
    assert session.pending_action is None
    assert session.last_resolved is not None
    assert session.last_resolved.account_ref == "CA2002USD"
    assert session.product_focus is not None
    assert session.product_focus.product_id == "CA2002USD"

    focus_before = session.product_focus.product_id
    r3 = asyncio.run(_turn("¿Qué significa disponible?", snap, session))
    assert r3 is not None
    assert "disponible" in (r3.text or "").lower()
    assert session.product_focus is not None
    assert session.product_focus.product_id == focus_before
    assert session.last_resolved.account_ref == "CA2002USD"

    r4 = asyncio.run(_turn("¿Y el saldo actual de esa cuenta?", snap, session))
    assert r4 is not None
    assert r4.account_ref == "CA2002USD"
    assert "350" in (r4.text or "")

    r5 = asyncio.run(_turn("No, ahora la de pesos", snap, session))
    assert r5 is not None
    assert r5.account_ref == "CA1001DOP"
    text5 = (r5.text or "").replace(",", "")
    assert "15200" in text5
    assert "DOP" in (r5.text or "") or "RD$" in (r5.text or "")


def test_variant_expressions_and_ambiguity(monkeypatch) -> None:
    monkeypatch.setenv("GENESIS_AZURE_BRAIN", "1")

    async def fake_draft(_q, text, **_kwargs):
        return text

    from genesis_cognitive.brain import turn_orchestrator

    monkeypatch.setattr(turn_orchestrator, "draft_natural_async", fake_draft)

    async def fake_classify(question, *, snapshot=None, session=None):
        return heuristic_intent(question, session)

    monkeypatch.setattr(turn_orchestrator, "classify_intent_async", fake_classify)

    snap = _snap()
    session = SessionState(customer_id="CLI-DUP", snapshot=snap)
    for phrase in ("la de usd", "la cuenta en dólares", "esa de dólares"):
        session.pending_action = PendingAction(
            intent_id="ACCOUNT_BALANCE_READ",
            capability_candidate="ACCOUNT_BALANCE",
            selected_route="PERSONAL_READ",
            detected_entities={"account_ref": None},
            missing_requirements=["account_ref"],
            suggested_question="¿Cuál cuenta?",
            original_question="dame el disponible",
            query_spec={"field": "available_balance", "scope": "single"},
        )
        r = asyncio.run(_turn(phrase, snap, session))
        assert r is not None
        assert r.account_ref == "CA2002USD"

    session.pending_action = PendingAction(
        intent_id="ACCOUNT_BALANCE_READ",
        capability_candidate="ACCOUNT_BALANCE",
        selected_route="PERSONAL_READ",
        detected_entities={"account_ref": None},
        missing_requirements=["account_ref"],
        suggested_question="¿Cuál?",
        original_question="disponible",
        query_spec={"field": "available_balance"},
    )
    missing = asyncio.run(_turn("la de euros", snap, session))
    assert missing is not None
    low = (missing.text or "").lower()
    assert "no encuentro" in low or "no tienes" in low or "portafolio" in low


def test_missing_balance_not_zero() -> None:
    snap = CustomerContextSnapshot(
        customer_id="X",
        display_name="Luis",
        default_currency="DOP",
        products=(
            ProductSnapshot(
                product_id="CA1",
                product_type="SAVINGS",
                alias="Ahorro",
                currency="DOP",
                status="active",
                available_balance=None,
                ledger_balance=None,
            ),
        ),
        loans=(),
    )
    packet = IntentPacket(
        "personal", "account", "available", confidence=0.9, source="heuristic",
    )
    result = execute_grounded(packet, snap, "disponible")
    low = (result.text or "").lower()
    assert "ausente" in low or "no está disponible" in low
    assert "RD$0" not in (result.text or "")


def test_ordinal_and_other_resolution() -> None:
    snap = _snap()
    session = SessionState(
        customer_id="CLI-DUP",
        snapshot=snap,
        pending_action=PendingAction(
            intent_id="ACCOUNT_BALANCE_READ",
            capability_candidate="ACCOUNT_BALANCE",
            selected_route="PERSONAL_READ",
            detected_entities={"account_ref": None},
            missing_requirements=["account_ref"],
            suggested_question="1) DOP 2) USD",
            original_question="disponible",
            query_spec={"field": "available_balance"},
        ),
    )
    first = resolve_product_reference("la primera", snap, session)
    assert first is not None and first.product_id == "CA1001DOP"
    session.last_resolved = LastResolved(
        intent_id="ACCOUNT_BALANCE_READ",
        account_ref="CA1001DOP",
        original_question="disponible",
    )
    remember_product_focus(session, "ACCOUNT_BALANCE_READ", "CA1001DOP", "disponible")
    other = resolve_product_reference("la otra", snap, session)
    assert other is not None and other.product_id == "CA2002USD"
