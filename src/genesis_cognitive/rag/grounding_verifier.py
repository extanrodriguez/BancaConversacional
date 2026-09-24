"""Verifier de grounding: cada claim de producto debe tener evidencia Search/KB.

No usa el LLM: valida aplicabilidad léxica/producto antes de declarar
respuesta grounded. Si falta evidencia → gap explícito (no inventar).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


def _norm(s: str) -> str:
    t = (s or "").lower()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Marcadores de producto (alineados con plan_executor / kb_package_ingest)
PRODUCT_MARKERS: dict[str, tuple[str, ...]] = {
    "visa_platinum": ("platinum", "platino"),
    "visa_infinite": ("infinite",),
    "visa_gold": ("gold",),
    "visa_joven": ("joven",),
    "visa_clasica": ("clasica", "clásica", "clasico"),
    "bravo": ("bravo",),
    "full_car": ("full car", "fullcar"),
    "pricesmart": ("pricesmart",),
    "multicredito": ("multicredit", "credito diferido", "crédito diferido"),
    "cuenta_ahorros": ("cuenta de ahorro", "cuenta ahorro", "ahorros"),
    "cuenta_corriente": ("cuenta corriente",),
}


def catalog_ref_key(ref: str | None) -> str:
    n = _norm(str(ref or "").replace("_", " "))
    if not n:
        return ""
    for key, markers in PRODUCT_MARKERS.items():
        if any(m in n for m in markers if len(m) >= 4) or key.replace("_", " ") in n:
            return key
    return n.replace(" ", "_")


def product_filter_terms(ref: str | None) -> str | None:
    """Término corto para filtro Search (product/title)."""
    key = catalog_ref_key(ref)
    if not key:
        return None
    markers = PRODUCT_MARKERS.get(key) or ()
    if markers:
        return markers[0]
    return key.replace("_", " ")


def evidence_supports_product(*, text: str, title: str = "", ref: str | None = None) -> bool:
    key = catalog_ref_key(ref)
    if not key:
        return bool((text or "").strip())
    markers = PRODUCT_MARKERS.get(key) or (key.replace("_", " "),)
    blob = _norm(f"{title} {text}")
    has_wanted = any(m in blob for m in markers if m)
    if not has_wanted:
        return False
    # rival explícito sin el pedido
    for other, om in PRODUCT_MARKERS.items():
        if other == key:
            continue
        if any(m in blob for m in om if len(m) >= 4) and not has_wanted:
            return False
    return True


@dataclass
class GroundingClaim:
    claim_id: str
    product_ref: str
    required: bool = True
    attribute: str | None = None  # tasa|beneficio|requisito|exclusion|procedure|features|None


@dataclass
class GroundingHit:
    claim_id: str
    product_ref: str
    grounded: bool
    doc_id: str | None = None
    title: str | None = None
    excerpt: str | None = None
    reason: str = ""
    attribute: str | None = None


@dataclass
class GroundingReport:
    ok: bool
    hits: list[GroundingHit] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "missing": list(self.missing),
            "notes": list(self.notes),
            "hits": [
                {
                    "claim_id": h.claim_id,
                    "product_ref": h.product_ref,
                    "grounded": h.grounded,
                    "doc_id": h.doc_id,
                    "title": h.title,
                    "reason": h.reason,
                    "attribute": h.attribute,
                }
                for h in self.hits
            ],
        }


# Marcadores léxicos mínimos por atributo afirmado (nombre de producto ≠ atributo)
ATTRIBUTE_MARKERS: dict[str, tuple[str, ...]] = {
    "rate": ("tasa", "interes", "interés", "tea", "tasa anual"),
    "benefit": ("beneficio", "beneficios", "cashback", "millas", "puntos", "lounge"),
    "requirement": ("requisito", "requisitos", "ingreso", "documentacion", "documentación"),
    "exclusion": ("exclusion", "exclusión", "no aplica", "exclu", "excepto"),
    "procedure": ("proceso", "procedimiento", "pasos", "solicitar", "cancel"),
    "features": ("caracteristic", "facilita", "instrumento", "permite", "condiciones"),
}


def evidence_supports_attribute(*, text: str, title: str = "", attribute: str | None) -> bool:
    """True si el texto respalda el atributo pedido (no basta el nombre del producto)."""
    if not attribute:
        return True
    markers = ATTRIBUTE_MARKERS.get(attribute) or (attribute,)
    blob = _norm(f"{title} {text}")
    return any(m in blob for m in markers if m)


def verify_product_claims(
    claims: list[GroundingClaim],
    *,
    evidence_by_ref: dict[str, dict[str, Any]],
) -> GroundingReport:
    """Verifica producto (+ atributo si se pide) contra evidencia.

    `evidence_by_ref`: product_ref -> {text, title?, doc_id?}
    """
    hits: list[GroundingHit] = []
    missing: list[str] = []
    notes: list[str] = []
    for claim in claims:
        ev = evidence_by_ref.get(claim.product_ref) or evidence_by_ref.get(
            catalog_ref_key(claim.product_ref)
        )
        text = str((ev or {}).get("text") or "")
        title = str((ev or {}).get("title") or "")
        if not text.strip():
            hits.append(
                GroundingHit(
                    claim_id=claim.claim_id,
                    product_ref=claim.product_ref,
                    grounded=False,
                    reason="no_evidence",
                    attribute=claim.attribute,
                )
            )
            if claim.required:
                missing.append(
                    f"{claim.product_ref}:{claim.attribute or 'product'}"
                )
            continue
        ok_prod = evidence_supports_product(text=text, title=title, ref=claim.product_ref)
        ok_attr = evidence_supports_attribute(
            text=text, title=title, attribute=claim.attribute
        )
        ok = ok_prod and ok_attr
        reason = "ok"
        if not ok_prod:
            reason = "product_mismatch"
        elif not ok_attr:
            reason = f"attribute_missing:{claim.attribute}"
            notes.append(
                f"Producto {claim.product_ref} recuperado pero sin soporte de atributo "
                f"'{claim.attribute}' (nombre ≠ hecho afirmado)."
            )
        hits.append(
            GroundingHit(
                claim_id=claim.claim_id,
                product_ref=claim.product_ref,
                grounded=ok,
                doc_id=(ev or {}).get("doc_id"),
                title=title or None,
                excerpt=text[:240] if ok else None,
                reason=reason,
                attribute=claim.attribute,
            )
        )
        if claim.required and not ok:
            missing.append(f"{claim.product_ref}:{claim.attribute or 'product'}")
    return GroundingReport(ok=not missing, hits=hits, missing=missing, notes=notes)


def verify_compare_set(
    refs: list[str],
    *,
    recovered: list[tuple[str, str]],
    attribute: str | None = "features",
) -> GroundingReport:
    """Atajo: lista (label, text) recuperada vs refs pedidas (+ atributo)."""
    by_ref: dict[str, dict[str, Any]] = {}
    for label, text in recovered:
        key = catalog_ref_key(label)
        by_ref[key] = {"text": text, "title": label}
        by_ref[label] = {"text": text, "title": label}
    claims = [
        GroundingClaim(
            claim_id=f"cmp-{i+1}",
            product_ref=r,
            required=True,
            attribute=attribute,
        )
        for i, r in enumerate(refs)
    ]
    for r in refs:
        key = catalog_ref_key(r)
        if key in by_ref and r not in by_ref:
            by_ref[r] = by_ref[key]
    return verify_product_claims(claims, evidence_by_ref=by_ref)
