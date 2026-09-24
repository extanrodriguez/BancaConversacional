"""Tests Foundry KB + ambigüedad (sin red)."""

from __future__ import annotations

from genesis_cognitive.rag.foundry_kb_agent import (
    ask_foundry_kb_agent,
    build_knowledge_ambiguity_clarification,
    is_foundry_kb_enabled,
    is_knowledge_ambiguous_question,
)
from genesis_cognitive.router.field_guardrails import apply_kb_knowledge_ambiguity_guardrail
from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot


def test_flag_off(monkeypatch) -> None:
    monkeypatch.setenv("GENESIS_FOUNDRY_KB_AGENT", "0")
    assert is_foundry_kb_enabled() is False


def test_certificado_ambiguo_clarifica() -> None:
    assert is_knowledge_ambiguous_question("certificado")
    msg = build_knowledge_ambiguity_clarification("certificado", "Felix")
    assert msg is not None
    assert "depósito" in msg.lower() or "deposito" in msg.lower()
    assert "garantía" in msg.lower() or "garantia" in msg.lower() or "préstamo" in msg.lower() or "prestamo" in msg.lower()


def test_kb_ambiguity_guardrail() -> None:
    snap = CustomerContextSnapshot(
        customer_id="T",
        display_name="Felix",
        default_currency="DOP",
        products=(),
        loans=(),
    )
    out = apply_kb_knowledge_ambiguity_guardrail(snap, "certificado")
    assert out is not None
    assert out[0] == "CLARIFICATION_REQUIRED"
    assert "Felix" in (out[2] or "")


def test_que_es_no_bloquea_por_ambiguity_guardrail() -> None:
    snap = CustomerContextSnapshot(
        customer_id="T",
        display_name="Felix",
        default_currency="DOP",
        products=(),
        loans=(),
    )
    out = apply_kb_knowledge_ambiguity_guardrail(snap, "que es un certificado de deposito")
    assert out is None


def test_skip_personal(monkeypatch) -> None:
    monkeypatch.setenv("GENESIS_FOUNDRY_KB_AGENT", "1")
    out = ask_foundry_kb_agent("cual es mi saldo")
    assert out["status"] == "FOUNDRY_SKIP_PERSONAL"
