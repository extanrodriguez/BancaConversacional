"""Fase 1 — moderación, alcance, FAQ corto, reclamaciones, institucional."""

from __future__ import annotations

from decimal import Decimal

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.router.faq_guardrail import clear_faq_cache, match_faq
from genesis_cognitive.router.field_guardrails import run_field_fastpath
from genesis_cognitive.router.moderation import moderate_user_text
from genesis_cognitive.router.reclamacion_guardrail import apply_reclamacion_guardrail
from genesis_cognitive.router.scope_guardrail import apply_scope_guardrail, is_assistant_scope_question
from genesis_cognitive.rag.local_rag import _human_case_fallback, _is_institutional_question


def _snap() -> CustomerContextSnapshot:
    products = (
        ProductSnapshot(
            product_id="11042010152142",
            product_type="SAVINGS",
            alias="Cuenta de Ahorros",
            currency="DOP",
            status="active",
            available_balance=Decimal("1000"),
        ),
        ProductSnapshot(
            product_id="250925031840000011",
            product_type="CREDIT_CARD",
            alias="Visa",
            currency="DOP",
            status="active",
            credit_limit=Decimal("100000"),
            card_mask="****3446",
        ),
    )
    return CustomerContextSnapshot(
        customer_id="TEST-F1",
        display_name="Cliente Prueba",
        default_currency="DOP",
        products=products,
        loans=(),
    )


def test_moderation_blocks_profanity_only() -> None:
    r = moderate_user_text("COÑO")
    assert r.is_offensive
    assert not r.has_functional_intent
    assert r.block_and_redirect

    hit = run_field_fastpath(_snap(), "COÑO", None)
    assert hit is not None
    st, _acts, txt, _sug, step, *_ = hit
    assert step == "moderation"
    assert st == "NON_OPERATIONAL"
    assert "consultas bancarias" in (txt or "").lower()
    assert "hola" not in (txt or "").lower()


def test_moderation_allows_profanity_with_balance_intent() -> None:
    r = moderate_user_text("coño dime mi saldo")
    assert r.is_offensive
    assert r.has_functional_intent
    assert not r.block_and_redirect


def test_scope_lists_capabilities() -> None:
    assert is_assistant_scope_question("¿en que me puedes ayudar?")
    out = apply_scope_guardrail(_snap(), "¿en que me puedes ayudar?")
    assert out is not None
    st, acts, txt, _ = out
    assert st == "VALID_CONTRACT"
    assert acts[0]["intent_id"] == "ASSISTANT_SCOPE"
    low = (txt or "").lower()
    assert "saldo" in low or "cuentas" in low
    assert "tarjeta" in low
    assert "transfer" in low  # indica que aún no hace transferencias

    hit = run_field_fastpath(_snap(), "en que me puedes ayudar", None)
    assert hit is not None
    assert hit[4] == "scope"


def test_faq_mision_short_and_long() -> None:
    clear_faq_cache()
    for q in ("Mision", "CUAL ES LA MISION", "¿Cuál es la misión del Banco?"):
        hit = match_faq(q)
        assert hit is not None, f"no FAQ match for {q!r}"
        assert "emprendedores" in (hit.get("answer") or "").lower() or "institución" in (
            hit.get("answer") or ""
        ).lower() or "institucion" in (hit.get("answer") or "").lower()

    fp = run_field_fastpath(_snap(), "Mision", None)
    assert fp is not None
    assert fp[4] in ("faq", "faq_rest")
    assert "emprendedor" in (fp[2] or "").lower() or "instituc" in (fp[2] or "").lower()


def test_faq_mision_y_vision_combinadas() -> None:
    """Pregunta compuesta no debe devolver solo misión (alucinación por top-1 FAQ)."""
    clear_faq_cache()
    for q in (
        "CUAL ES LA MISIÓN Y LA VISIÓN DE BANCO SANTA CRU?",
        "cual es la mision y la vision del banco",
        "dime la mision y la vision",
    ):
        hit = match_faq(q)
        assert hit is not None, f"no FAQ match for {q!r}"
        ans = (hit.get("answer") or "").lower()
        assert "emprendedor" in ans or "instituc" in ans
        assert "preferido" in ans, f"falta visión en respuesta para {q!r}"
        assert "visión" in (hit.get("topic") or "").lower() or "vision" in (
            hit.get("topic") or ""
        ).lower() or "+" in str(hit.get("id") or "")


def test_faq_banco_santa_cruz_and_hablame() -> None:
    clear_faq_cache()
    for q in ("QUE ES BANCO SANTA CRUZ", "hablame del banco", "Qué es BSC"):
        hit = match_faq(q)
        assert hit is not None, f"no FAQ match for {q!r}"
        assert "santa cruz" in (hit.get("answer") or "").lower() or "emprendedor" in (
            hit.get("answer") or ""
        ).lower()

    fp = run_field_fastpath(_snap(), "hablame del banco", None)
    assert fp is not None
    assert fp[4] == "faq"
    assert "asesor se pondra" not in (fp[2] or "").lower()


def test_bank_catalog_not_personal_portfolio() -> None:
    """Preguntas del catálogo del banco no deben listar productos del cliente."""
    clear_faq_cache()
    from genesis_cognitive.router.field_guardrails import (
        is_bank_catalog_question,
        is_portfolio_list_question,
    )

    for q in (
        "cuales son los productos que tiene el banco",
        "cuales cuentas tiene el banco",
        "que productos ofrece el banco",
    ):
        assert is_bank_catalog_question(q), q
        assert not is_portfolio_list_question(q), q
        fp = run_field_fastpath(_snap(), q, None)
        assert fp is not None, q
        # bank_catalog (preferido) o faq: ambos son conocimiento institucional, no portafolio
        assert fp[4] in ("faq", "bank_catalog"), (q, fp[4], (fp[2] or "")[:80])
        low = (fp[2] or "").lower()
        assert "portafolio" not in low or "solicitar" in low or "contratar" in low or "cuenta" in low
        assert "1000" not in (fp[2] or "")  # no saldo personal


def test_mis_certificados_list_dap() -> None:
    """En RD 'certificados' = depósitos a plazo del portafolio."""
    from genesis_cognitive.router.field_guardrails import is_portfolio_list_question

    products = _snap().products + (
        ProductSnapshot(
            product_id="CD5511",
            product_type="TERM_DEPOSIT",
            alias="Certificado de Depósito",
            currency="DOP",
            status="active",
            available_balance=Decimal("180755.33"),
            interest_rate=Decimal("8.15"),
            maturity_date="2026-09-19",
        ),
    )
    snap = CustomerContextSnapshot(
        customer_id="TEST-F1",
        display_name="Cliente Prueba",
        default_currency="DOP",
        products=products,
        loans=(),
    )
    for q in ("dame mis certificados", "cuales son mis certificados", "mis certificados de deposito"):
        assert is_portfolio_list_question(q), q
        fp = run_field_fastpath(snap, q, None)
        assert fp is not None, q
        assert fp[4] == "portfolio", (q, fp[4])
        low = (fp[2] or "").lower()
        assert "certificado" in low or "depósito" in low or "deposito" in low
        assert "5511" in (fp[2] or "") or "180" in (fp[2] or "")


def test_retiro_fondos_cliente_fallecido_faq() -> None:
    """No debe caer en transfer UNSUPPORTED; debe responder KB vf01-r324."""
    clear_faq_cache()
    from genesis_cognitive.router.field_guardrails import is_transfer_question

    q = "PROCESO DE RETIRO DE FONDO DEL CLIENTE FALLECIDO"
    assert not is_transfer_question(q)
    hit = match_faq(q)
    assert hit is not None
    assert "fallecid" in (hit.get("topic") or "").lower() or hit.get("id") == "vf01-r324"
    fp = run_field_fastpath(_snap(), q, None)
    assert fp is not None
    assert fp[4] == "faq", (fp[4], (fp[2] or "")[:120])
    low = (fp[2] or "").lower()
    assert "fallecid" in low or "sucesor" in low or "defunci" in low
    assert "aún no tengo habilitados" not in low
    assert "aun no tengo habilitados" not in low


def test_reclamacion_asks_channel_then_answers() -> None:
    snap = _snap()
    first = apply_reclamacion_guardrail(snap, "¿cual es el proceso para una reclamacion?")
    assert first is not None
    st, acts, txt, _ = first
    # Overview KB inmediato + oferta de canal (ya no fuerza clarificación vacía)
    assert st == "VALID_CONTRACT"
    assert "809" in (txt or "") or "canal" in (txt or "").lower() or "reclam" in (txt or "").lower()
    assert acts[0].get("intent_id") in (
        "BUSINESS_KNOWLEDGE_QUERY",
        "RECLAMACION_OVERVIEW",
        "RECLAMACION_CHANNEL",
    ) or (acts[0].get("detected_entities") or {}).get("knowledge_topic") in (
        "RECLAMACION_CHANNEL",
        "RECLAMACION_OVERVIEW",
        None,
    )

    fp1 = run_field_fastpath(snap, "proceso para una reclamacion", None)
    assert fp1 is not None
    assert fp1[0] == "VALID_CONTRACT"
    assert fp1[4] == "reclamacion"

    second = apply_reclamacion_guardrail(
        snap, "Centro de Contacto", pending_topic="RECLAMACION_CHANNEL",
    )
    assert second is not None
    st2, _a2, txt2, _ = second
    assert st2 == "VALID_CONTRACT"
    assert "809.726.1000" in (txt2 or "")

    fp2 = run_field_fastpath(
        snap, "Centro de Contacto", None, pending_knowledge_topic="RECLAMACION_CHANNEL",
    )
    assert fp2 is not None
    assert fp2[0] == "VALID_CONTRACT"
    assert "809" in (fp2[2] or "")


def test_institutional_rag_fallback_not_human_case() -> None:
    assert _is_institutional_question("hablame del banco")
    msg = _human_case_fallback("hablame del banco", "c1", "Ana")
    assert "asesor se pondra" not in msg.lower()
    assert "banco santa cruz" in msg.lower() or "instituc" in msg.lower()
