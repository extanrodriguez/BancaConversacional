"""P0 puerta confianza + P1 cache Foundry."""

from __future__ import annotations

from pathlib import Path

import pytest

from genesis_cognitive.router.knowledge_followup import (
    prefer_foundry_for_faq_hit,
    should_prefer_foundry_over_faq,
)
from genesis_cognitive.rag import foundry_kb_cache as cache_mod


def test_should_prefer_foundry_when_answer_generic() -> None:
    q = "¿Y qué requisitos tiene?"
    a = "Crédito Diferido: producto integral que vincula Multicrédito y Cuotas BSC."
    assert should_prefer_foundry_over_faq(q, a) is True
    assert prefer_foundry_for_faq_hit(q, a, score=0.95) is True


def test_prefer_foundry_gate_off_keeps_high_score_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GENESIS_KB_CONFIDENCE_GATE", raising=False)
    q = "¿Qué es Crédito Diferido?"
    a = "Crédito Diferido: producto integral que vincula Multicrédito y Cuotas BSC."
    assert prefer_foundry_for_faq_hit(q, a, score=0.7) is False


def test_prefer_foundry_gate_on_detail_low_score(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_KB_CONFIDENCE_GATE", "1")
    monkeypatch.setenv("GENESIS_FAQ_HIGH_SCORE", "0.90")
    monkeypatch.setenv("GENESIS_FAQ_GRAY_MIN", "0.55")
    q = "¿Cómo lo solicito?"
    # Respuesta que sí menciona solicitud → should_prefer False, pero score bajo + detalle → Foundry
    a = "Puedes solicitar el producto en canales digitales o en un centro de negocios."
    assert should_prefer_foundry_over_faq(q, a) is False
    assert prefer_foundry_for_faq_hit(q, a, score=0.72) is True
    assert prefer_foundry_for_faq_hit(q, a, score=0.92) is False


def test_foundry_cache_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GENESIS_FOUNDRY_CACHE", "1")
    monkeypatch.setenv("GENESIS_FOUNDRY_CACHE_TTL_S", "3600")
    monkeypatch.setenv("GENESIS_FOUNDRY_CACHE_DIR", str(tmp_path))
    q = "¿Qué requisitos tiene Crédito Diferido?"
    topic = "Crédito Diferido"
    assert cache_mod.get_cached(q, topic=topic) is None
    cache_mod.put_cached(
        q,
        {
            "ok": True,
            "answer": "Presentar cédula y tener tarjeta del banco.",
            "status": "FOUNDRY_KB_ANSWERED",
            "agent": "genesis-kb-agent-poc",
            "version": "5",
        },
        topic=topic,
    )
    hit = cache_mod.get_cached(q, topic=topic)
    assert hit is not None
    assert hit["status"] == "FOUNDRY_KB_CACHE_HIT"
    assert "cédula" in hit["answer"].lower() or "cedula" in hit["answer"].lower()


def test_foundry_cache_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GENESIS_FOUNDRY_CACHE", raising=False)
    monkeypatch.setenv("GENESIS_FOUNDRY_CACHE_DIR", str(tmp_path))
    cache_mod.put_cached(
        "pregunta",
        {"ok": True, "answer": "x", "status": "FOUNDRY_KB_ANSWERED"},
        topic="t",
    )
    assert cache_mod.get_cached("pregunta", topic="t") is None
