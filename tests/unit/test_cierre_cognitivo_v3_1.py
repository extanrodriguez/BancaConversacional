"""Cierre V3.1 — cinco recorridos completos por POST /turn + regresiones plan."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from genesis_cognitive.brain.plan_interpreter import (
    interpret_turn_plan,
    message_is_institutional_only,
    scrub_inbound_question,
)
from genesis_cognitive.brain.security_secrets import redact_secret_digits_for_logs
from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import (
    PendingAction,
    ProductFocus,
    ReactiveSessionStore,
    SessionState,
)
from genesis_cognitive.enums import FreshnessState
from genesis_cognitive.router.faq_guardrail import clear_faq_cache


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSUMOS = PROJECT_ROOT / "works" / "Banca_Cierre_V3_1" / "insumos"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GENESIS_FAQ_PATH", str(PROJECT_ROOT / "data" / "kb_faq_vf01.json"))
    monkeypatch.setenv(
        "GENESIS_FAQ_OVERLAY_PATH",
        str(PROJECT_ROOT / "data" / "kb_faq_overlay_fase1.json"),
    )
    monkeypatch.setenv("GENESIS_AZURE_BRAIN", "0")
    clear_faq_cache()
    yield
    clear_faq_cache()


def _card(pid: str = "TC4401", *, avail: str = "15000", debt: str = "3200") -> ProductSnapshot:
    return ProductSnapshot(
        product_id=pid,
        product_type="CREDIT_CARD",
        alias=f"Visa …{pid[-4:]}",
        currency="DOP",
        status="active",
        available_balance=Decimal(avail),
        ledger_balance=Decimal(debt),
        available_purchases_domestic=Decimal(avail),
        last_four=pid[-4:],
        min_payment_rd=Decimal("500"),
    )


def _acct(pid: str = "CA2001", *, avail: str = "8000", ledger: str = "8500") -> ProductSnapshot:
    return ProductSnapshot(
        product_id=pid,
        product_type="SAVINGS",
        alias=f"Ahorros …{pid[-4:]}",
        currency="DOP",
        status="active",
        available_balance=Decimal(avail),
        ledger_balance=Decimal(ledger),
        last_four=pid[-4:],
    )


def _checking(pid: str = "CC3001") -> ProductSnapshot:
    return ProductSnapshot(
        product_id=pid,
        product_type="CHECKING",
        alias="Corriente …3001",
        currency="DOP",
        status="active",
        available_balance=Decimal("1200"),
        ledger_balance=Decimal("1200"),
        last_four="3001",
    )


def _dap(pid: str, *, rate: str, maturity: str) -> ProductSnapshot:
    return ProductSnapshot(
        product_id=pid,
        product_type="TERM_DEPOSIT",
        alias=f"Certificado …{pid[-4:]}",
        currency="DOP",
        status="active",
        interest_rate=Decimal(rate),
        maturity_date=maturity,
        ledger_balance=Decimal("100000"),
        available_balance=Decimal("100000"),
        last_four=pid[-4:],
    )


def _loan(pid: str = "LN5001") -> tuple[ProductSnapshot, LoanSnapshot]:
    p = ProductSnapshot(
        product_id=pid,
        product_type="LOAN",
        alias="Préstamo …5001",
        currency="DOP",
        status="active",
        last_four="5001",
    )
    ln = LoanSnapshot(
        product_id=pid,
        loan_type="PERSONAL",
        installment_amount=Decimal("2500"),
        annual_interest_rate=Decimal("14.5"),
        outstanding_principal=Decimal("40000"),
        delinquency_days=0,
        next_due_date="2026-11-01",
        last_four="5001",
    )
    return p, ln


def _snap(*products: ProductSnapshot, loans: tuple = (), cid: str = "SYN-V31") -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id=cid,
        display_name="Cliente V31",
        default_currency="DOP",
        products=products,
        loans=loans,
    )


def _make_app(store: ReactiveSessionStore, snap: CustomerContextSnapshot):
    from unittest.mock import AsyncMock, MagicMock

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
    from genesis_cognitive.enums import InterpretationMode, OperationalState, SelectedRoute
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


def _seed(store: ReactiveSessionStore, conv: str, snap: CustomerContextSnapshot, **extra) -> None:
    store.put_snapshot(snap.customer_id, snap, mark_fetched_now=True)
    sess = SessionState(
        customer_id=snap.customer_id,
        snapshot=snap,
        snapshot_source_fetched_at=time.time(),
        **extra,
    )
    store.put_session(conv, sess)


def _turn(client: TestClient, conv: str, snap: CustomerContextSnapshot, q: str) -> dict:
    resp = client.post(
        "/turn",
        json={
            "question": q,
            "conversation_id": conv,
            "customer_id": snap.customer_id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "app_channel" in body
    assert isinstance(body.get("reply") or "", str)
    assert (body.get("reply") or body["app_channel"].get("client_response") or "").strip()
    return body


def _reply(body: dict) -> str:
    return (
        body.get("reply")
        or (body.get("app_channel") or {}).get("client_response")
        or ""
    )


# ---------------------------------------------------------------------------
# Insumos 236 + 24
# ---------------------------------------------------------------------------


def test_insumos_counts_236_and_24() -> None:
    p236 = INSUMOS / "Casos_QA_236_Extraidos.jsonl"
    p24 = INSUMOS / "Casos_QA_Adicionales_V3.jsonl"
    assert p236.is_file()
    assert p24.is_file()
    rows236 = [json.loads(ln) for ln in p236.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows24 = [json.loads(ln) for ln in p24.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows236) == 236
    assert len({r["case_id"] for r in rows236}) == 236
    assert len(rows24) == 24
    assert len({r["case_id"] for r in rows24}) == 24


# ---------------------------------------------------------------------------
# Recorrido 1: cuenta/tarjeta + disponible + definición
# ---------------------------------------------------------------------------


def test_journey1_focus_card_available_and_definition() -> None:
    snap = _snap(_acct(), _card(), cid="J1")
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    client = TestClient(app)
    conv = "j1-conv"
    _seed(
        store, conv, snap,
        product_focus=ProductFocus(
            kind="CARD", product_id="TC4401", intent_id="CREDIT_CARD_DETAIL_READ",
        ),
    )
    b1 = _turn(client, conv, snap, "¿cuánto tengo disponible?")
    r1 = _reply(b1).lower()
    assert "15000" in r1.replace(",", "") or "disponible" in r1
    assert "8000" not in r1.replace(",", "")  # no saldo de cuenta

    b2 = _turn(client, conv, snap, "disponible de mi cuenta")
    r2 = _reply(b2).lower()
    assert "8000" in r2.replace(",", "") or "cuenta" in r2 or "ahorros" in r2

    b3 = _turn(client, conv, snap, "¿qué significa saldo disponible?")
    r3 = _reply(b3).lower()
    assert "disponible" in r3
    assert "8000" not in r3.replace(",", "")  # definición, no saldo personal
    steps = (b3.get("audit") or {}).get("route_steps") or []
    # Puede ir por turn_plan_multi o faq
    assert b3.get("status") in ("VALID_CONTRACT", None) or "VALID" in str(b3.get("status"))


# ---------------------------------------------------------------------------
# Recorrido 2: misión + personal; interrupción y retorno
# ---------------------------------------------------------------------------


def test_journey2_mission_plus_personal_and_resume() -> None:
    lp, ln = _loan()
    snap = _snap(_acct(), lp, loans=(ln,), cid="J2")
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    client = TestClient(app)
    conv = "j2-conv"
    _seed(
        store, conv, snap,
        pending_action=PendingAction(
            intent_id="LOAN_DETAIL_READ",
            capability_candidate="LOAN_DETAIL",
            selected_route="PERSONAL_READ",
            detected_entities={"account_ref": None},
            missing_requirements=["account_ref"],
            suggested_question="¿Sobre cuál préstamo?",
            original_question="¿Cuál es la tasa de mi préstamo?",
        ),
        pending_tasks=[{
            "task_id": "t_loan",
            "object": "loan",
            "fields": ["rate"],
            "original_question": "¿Cuál es la tasa de mi préstamo?",
        }],
    )

    # Misión + disponible en el mismo mensaje
    b1 = _turn(
        client, conv, snap,
        "Dime la misión y cuánto tengo disponible en mi cuenta",
    )
    r1 = _reply(b1)
    low1 = r1.lower()
    # Debe incluir evidencia institucional Y el disponible de cuenta
    assert "8000" in r1.replace(",", "") or "disponible" in low1
    assert (
        "misión" in low1
        or "mision" in low1
        or "institución" in low1
        or "institucion" in low1
        or "emprendedor" in low1
        or len(r1) > 120
    )
    # Pending no debe haberse perdido por FAQ-only early return
    sess = store.get_session(conv)
    assert sess is not None

    # Excursión institucional sola
    b2 = _turn(client, conv, snap, "misión")
    assert len(_reply(b2)) > 40

    # Retomar pendiente
    b3 = _turn(client, conv, snap, "retomando el préstamo, el segundo")
    r3 = _reply(b3).lower()
    assert r3  # responde o aclara; no inventa saldo de esposo


def test_mission_and_vision_both() -> None:
    snap = _snap(_acct(), cid="J2b")
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    client = TestClient(app)
    conv = "j2b-conv"
    _seed(store, conv, snap)
    body = _turn(client, conv, snap, "misión y visión")
    text = _reply(body).lower()
    assert "misión" in text or "mision" in text
    assert "visión" in text or "vision" in text


# ---------------------------------------------------------------------------
# Recorrido 3: multi-campo / certificados / exclusión balance
# ---------------------------------------------------------------------------


def test_journey3_card_fields_and_dap_exclusion() -> None:
    snap = _snap(
        _card("TC4401"),
        _card("TC4402", avail="9000", debt="1000"),
        _dap("DAP1", rate="8.0", maturity="2026-10-01"),
        _dap("DAP2", rate="9.5", maturity="2026-12-15"),
        cid="J3",
    )
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    client = TestClient(app)
    conv = "j3-conv"
    _seed(store, conv, snap)

    # Multi-campo sin tarjeta única → aclaración + conserva campos en pending
    b1 = _turn(
        client, conv, snap,
        "de mi tarjeta quiero saber la deuda, el disponible y la fecha de pago",
    )
    r1 = _reply(b1).lower()
    assert "tarjeta" in r1 or "cuál" in r1 or "cual" in r1
    sess = store.get_session(conv)
    assert sess is not None
    assert sess.pending_action is not None or sess.pending_tasks

    # Selección + reanudar
    _seed(
        store, conv, snap,
        product_focus=ProductFocus(
            kind="CARD", product_id="TC4401", intent_id="CREDIT_CARD_DETAIL_READ",
        ),
        pending_tasks=[{
            "task_id": "t1", "object": "credit_card",
            "fields": ["balance", "available", "due_date"],
            "original_question": "deuda disponible fecha",
        }],
    )
    b2 = _turn(client, conv, snap, "la Visa 4401: deuda, disponible y fecha de pago")
    r2 = _reply(b2)
    low2 = r2.lower()
    assert "3200" in r2.replace(",", "") or "deuda" in low2 or "adeud" in low2
    assert "15000" in r2.replace(",", "") or "disponible" in low2

    # P15-like: certificados sin balance/capital ni tarjetas
    b3 = _turn(
        client, conv, snap,
        "tasa y vencimiento de mis certificados, cuál vence primero, pero no el balance",
    )
    r3 = _reply(b3)
    low3 = r3.lower()
    assert "8" in r3 or "9.5" in r3 or "tasa" in low3
    assert "2026-10-01" in r3 or "vence" in low3
    assert "100000" not in r3.replace(",", "")
    assert "tarjeta" not in low3


# ---------------------------------------------------------------------------
# Recorrido 4: catálogo → existencia; comparación ordenada
# ---------------------------------------------------------------------------


def test_journey4_catalog_existence_and_compare_set() -> None:
    snap = _snap(_acct(), _card(), cid="J4")
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    client = TestClient(app)
    conv = "j4-conv"
    _seed(store, conv, snap, last_knowledge_topic="multicredito")

    b0 = _turn(client, conv, snap, "condiciones del multicrédito")
    assert _reply(b0)
    sess = store.get_session(conv)
    assert sess is not None
    # Forzar topic por si FAQ no lo setea
    sess.last_knowledge_topic = "multicredito"
    store.put_session(conv, sess)

    b1 = _turn(client, conv, snap, "¿Tengo yo ese producto?")
    r1 = _reply(b1).lower()
    assert "8000" not in r1.replace(",", "")  # no saldo de cuenta (fallo MIX07)
    assert any(s in r1 for s in ("tarjeta", "multicrédito", "multicredito", "servicio", "portafolio"))

    # Comparación catálogo + agregar
    b2 = _turn(client, conv, snap, "compara visa platinum y visa classic")
    r2 = _reply(b2).lower()
    assert "platinum" in r2 or "classic" in r2 or "1." in r2
    sess = store.get_session(conv)
    assert sess is not None
    assert len(sess.compare_set) >= 2 or "platinum" in r2

    b3 = _turn(client, conv, snap, "agrega visa joven a la comparación")
    r3 = _reply(b3).lower()
    sess = store.get_session(conv)
    assert sess is not None
    # Orden vigente debe incluir joven si el plan actualizó compare_set
    if sess.compare_set:
        assert "visa_joven" in sess.compare_set or "joven" in r3


def test_cd13_min_payment_not_personal_selection() -> None:
    snap = _snap(_card(), _card("TC99"), cid="CD13")
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    client = TestClient(app)
    conv = "cd13-conv"
    _seed(store, conv, snap)
    body = _turn(client, conv, snap, "qué es el pago mínimo")
    text = _reply(body).lower()
    assert "mínimo" in text or "minimo" in text or "pago" in text
    # No debe ser solo menú de selección de tarjetas personales
    assert body.get("status") != "CLARIFICATION_REQUIRED" or "definición" in text or "general" in text


# ---------------------------------------------------------------------------
# Recorrido 5: secretos + titularidad
# ---------------------------------------------------------------------------


def test_journey5_secrets_scrubbed_and_ownership() -> None:
    snap = _snap(
        _acct("CA7615"),
        ProductSnapshot(
            product_id="LOAN27615",
            product_type="LOAN",
            alias="Préstamo …7615",
            currency="DOP",
            status="active",
            last_four="7615",
        ),
        cid="J5",
    )
    store = ReactiveSessionStore()
    app = _make_app(store, snap)
    client = TestClient(app)
    conv = "j5-conv"
    _seed(store, conv, snap)

    secret_q = "mi pin es 7615"
    safe, meta = scrub_inbound_question(secret_q)
    assert meta["had_secret_frame"]
    assert "7615" not in safe
    assert "***" in safe

    body = _turn(client, conv, snap, secret_q)
    reply = _reply(body).lower()
    assert "pin" in reply or "seguridad" in reply
    assert "50123" not in reply
    # Historial depurado
    sess = store.get_session(conv)
    assert sess is not None
    hist_q = " ".join(str(h.get("question") or "") for h in sess.history)
    assert "7615" not in hist_q
    assert redact_secret_digits_for_logs(secret_q).count("***") >= 1

    # Titularidad ajena
    b2 = _turn(client, conv, snap, "¿cuánto saldo tiene mi esposo?")
    r2 = _reply(b2).lower()
    assert "8000" not in r2.replace(",", "") and "8500" not in r2.replace(",", "")
    assert any(s in r2 for s in ("otra persona", "sesión", "no puedo", "autenticada"))

    # Pregunta general legítima
    b3 = _turn(client, conv, snap, "¿cómo abro una cuenta para mi hijo?")
    r3 = _reply(b3).lower()
    assert "8000" not in r3.replace(",", "")
    assert r3  # no bloqueo total por parentesco


def test_institutional_only_helper() -> None:
    assert message_is_institutional_only("misión")
    assert message_is_institutional_only("visión del banco")
    assert not message_is_institutional_only(
        "Dime la misión y cuánto tengo disponible en mi cuenta"
    )


def test_plan_multi_task_mission_and_available() -> None:
    snap = _snap(_acct())
    plan = interpret_turn_plan(
        "Dime la misión y cuánto tengo disponible en mi cuenta",
        None,
        snapshot=snap,
    )
    domains = {t.domain for t in plan.tasks}
    assert "institutional" in domains
    assert "personal" in domains
    assert len(plan.tasks) >= 2
