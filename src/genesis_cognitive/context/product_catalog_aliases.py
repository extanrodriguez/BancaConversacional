"""Catálogo de alias del paquete Potenciación Lunes.

Resuelve selectores comerciales (Joven, Gold, Multicrédito…) contra el
portafolio autenticado. El catálogo no prueba tenencia ni inventa códigos Core.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_FAMILY_TO_TYPES = {
    "tarjeta_credito": {"CREDIT_CARD"},
    "tarjeta_debito": {"DEBIT_CARD", "SAVINGS", "CHECKING", "PAYROLL"},
    "cuenta_ahorro": {"SAVINGS", "PAYROLL"},
    "cuenta_corriente": {"CHECKING"},
    "prestamo": {"LOAN"},
    "certificado": {"TERM_DEPOSIT"},
    "multicredito": {"CREDIT_CARD"},
}


def _default_catalog_path() -> Path:
    env = (os.getenv("GENESIS_PRODUCT_ALIAS_CATALOG") or "").strip()
    if env:
        return Path(env)
    return (
        Path(__file__).resolve().parents[3]
        / "works"
        / "insumos"
        / "BSC_Potenciacion_Lunes"
        / "catalogo"
        / "productos_alias.json"
    )


def _norm(text: str) -> str:
    t = (text or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


@lru_cache(maxsize=2)
def load_product_alias_catalog(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else _default_catalog_path()
    if not p.is_file():
        return {"version": None, "products": []}
    return json.loads(p.read_text(encoding="utf-8"))


def clear_alias_catalog_cache() -> None:
    load_product_alias_catalog.cache_clear()


def catalog_matches_for_text(question: str) -> list[dict[str, Any]]:
    """Entradas de catálogo cuyo alias aparece en la pregunta."""
    qn = _norm(question)
    if not qn:
        return []
    hits: list[dict[str, Any]] = []
    for prod in load_product_alias_catalog().get("products") or []:
        aliases = [_norm(a) for a in (prod.get("aliases") or []) if a]
        name = _norm(str(prod.get("name") or ""))
        scored = []
        for a in aliases + ([name] if name else []):
            if not a or len(a) < 3:
                continue
            if a == qn or f" {a} " in f" {qn} " or a in qn:
                scored.append(len(a))
        if scored:
            hits.append({**prod, "_alias_score": max(scored)})
    hits.sort(key=lambda x: int(x.get("_alias_score") or 0), reverse=True)
    return hits


def resolve_portfolio_by_catalog(
    question: str,
    products: list[Any],
) -> tuple[list[Any], str]:
    """Filtra productos del snapshot por alias de catálogo.

    Returns:
        (candidatos, motivo)
        motivo: unique | ambiguous_family | ambiguous | none | catalog_miss
    """
    active = [p for p in products if str(getattr(p, "status", "")).lower() == "active"]
    if not active:
        return [], "none"
    matches = catalog_matches_for_text(question)
    if not matches:
        return [], "catalog_miss"

    # Si la pregunta discrimina crédito/débito, restringir familia
    qn = _norm(question)
    prefer_credit = any(s in qn for s in ("credito", "debo", "adeud", "disponible", "limite", "límite"))
    prefer_debit = "debito" in qn and "credito" not in qn

    selected_entries = matches
    if prefer_debit:
        selected_entries = [m for m in matches if m.get("family") == "tarjeta_debito"] or matches
    elif prefer_credit:
        selected_entries = [m for m in matches if m.get("family") == "tarjeta_credito"] or matches

    # Tomar el alias más específico y sus familias posibles
    top_score = int(selected_entries[0].get("_alias_score") or 0)
    top = [m for m in selected_entries if int(m.get("_alias_score") or 0) >= top_score - 2]
    families = {str(m.get("family") or "") for m in top}

    candidates: list[Any] = []
    for p in active:
        pt = str(getattr(p, "product_type", "") or "")
        alias = _norm(str(getattr(p, "alias", "") or ""))
        for m in top:
            fam = str(m.get("family") or "")
            allowed = _FAMILY_TO_TYPES.get(fam, set())
            # CREDIT_CARD también cubre multicrédito
            if allowed and pt not in allowed and not (
                fam in ("tarjeta_credito", "multicredito") and pt == "CREDIT_CARD"
            ):
                continue
            # Match por tokens del nombre/alias catálogo en el alias del producto
            cat_aliases = [_norm(a) for a in (m.get("aliases") or []) if a]
            cat_aliases.append(_norm(str(m.get("name") or "")))
            for ca in cat_aliases:
                if not ca:
                    continue
                tokens = [t for t in ca.split() if len(t) >= 4 and t not in {
                    "tarjeta", "credito", "debito", "cuenta", "visa", "banco", "santa", "cruz",
                }]
                if tokens and all(tok in alias for tok in tokens[-2:]):
                    if p not in candidates:
                        candidates.append(p)
                    break
                if any(len(tok) >= 5 and tok in alias for tok in tokens):
                    if p not in candidates:
                        candidates.append(p)
                    break

    if not candidates:
        return [], "none"
    if len(candidates) == 1:
        return candidates, "unique"
    # Crédito y débito Joven a la vez
    types = {str(getattr(p, "product_type", "")) for p in candidates}
    if "CREDIT_CARD" in types and types - {"CREDIT_CARD"}:
        return candidates, "ambiguous_family"
    if len(families) > 1:
        return candidates, "ambiguous_family"
    return candidates, "ambiguous"
