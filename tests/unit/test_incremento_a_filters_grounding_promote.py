"""Unit tests Incremento A: promote approval, grounding attribute, filter no-strip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_promote_apply_requires_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from genesis_cognitive.learning import feedback_store as fs

    db = tmp_path / "fb.sqlite3"
    monkeypatch.setenv("GENESIS_LEARNING_DB", str(db))
    fs.init_db(db)
    ev = fs.FeedbackEvent(
        question="qué es visa joven",
        matched_id=None,
        matched_topic=None,
        score=0.0,
        ok=False,
        corrected_id="fase1-visa-joven",
        source="unit",
    )
    r1 = fs.record_feedback(ev, db)
    r2 = fs.record_feedback(ev, db)
    assert r1["recorded"] is True
    assert r2["duplicate"] is True  # no inflación de votos por re-run

    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({"entries": []}), encoding="utf-8")
    # dry: script rejects --apply without approved-json
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "promote_learning_expressions.py"),
            "--apply",
            "--min-votes",
            "1",
            "--overlay",
            str(overlay),
        ],
        capture_output=True,
        text=True,
        cwd=str(root),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "GENESIS_LEARNING_DB": str(db)},
    )
    assert proc.returncode == 2
    assert "approved-json" in (proc.stderr + proc.stdout).lower() or "aprobación" in (
        proc.stderr + proc.stdout
    ).lower()


def test_grounding_attribute_requires_more_than_product_name() -> None:
    from genesis_cognitive.rag.grounding_verifier import (
        GroundingClaim,
        evidence_supports_attribute,
        verify_product_claims,
    )

    # Solo nombre de producto, sin tasa
    text = "La Tarjeta Visa Platinum es un producto del banco."
    assert evidence_supports_attribute(text=text, attribute="rate") is False
    assert evidence_supports_attribute(
        text="Visa Platinum tiene tasa de interés preferencial", attribute="rate"
    )

    report = verify_product_claims(
        [
            GroundingClaim(
                claim_id="1",
                product_ref="visa_platinum",
                attribute="rate",
                required=True,
            )
        ],
        evidence_by_ref={
            "visa_platinum": {"text": text, "title": "Visa Platinum"},
        },
    )
    assert report.ok is False
    assert any("attribute_missing" in (h.reason or "") for h in report.hits)


def test_grounding_compare_partial_missing_product() -> None:
    from genesis_cognitive.rag.grounding_verifier import verify_compare_set

    g = verify_compare_set(
        ["visa_platinum", "visa_infinite"],
        recovered=[
            (
                "Visa Platinum",
                "Tarjeta Platinum instrumento de pago que te permite consumos.",
            )
        ],
        attribute="features",
    )
    assert g.ok is False
    assert any("infinite" in m for m in g.missing)


def test_search_filter_not_stripped_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si Search responde 400 con filtro, no reintenta sin filtro."""
    import genesis_cognitive.rag.azure_search_retrieve as mod

    monkeypatch.setenv("GENESIS_SEARCH_RETRIEVE", "1")
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://example.search.windows.net")
    monkeypatch.setenv("AZURE_SEARCH_INDEX", "bsc-kb-qa-vnext-20260921")
    monkeypatch.setenv("AZURE_SEARCH_API_KEY", "fake")
    monkeypatch.setenv("GENESIS_SEARCH_RERANK_LOCAL", "0")

    class _Resp:
        status_code = 400
        def json(self):
            return {"error": "bad filter"}

    class _Client:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, *a, **k):
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(mod, "_index_has_vector", lambda: False)
    out = mod.azure_search_retrieve(
        "platinum", product_filter="platinum", document_types=["product_knowledge"]
    )
    assert out["error"] and "filter_required" in out["error"]
    assert out.get("filter_stripped") is False
    assert out.get("filter_fallback") is None
