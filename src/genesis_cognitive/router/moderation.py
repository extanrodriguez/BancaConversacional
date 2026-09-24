"""Moderación de lenguaje ofensivo — Capa 0 del orquestador.

Detecta groserías / insultos sin depender de placeholders FAQ ([grosería]).
Diseñado para ejecutarse ANTES del fast-path FAQ/LLM.

Env (contenedores):
  GENESIS_PROFANITY_EXTRA  — lista separada por comas de términos adicionales
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


# Términos base (español dominicano / regional + variantes comunes).
# No es exhaustivo a propósito: se puede ampliar por env sin redeploy de imagen
# montando override o GENESIS_PROFANITY_EXTRA.
_BASE_PROFANITY = frozenset(
    {
        "cono",
        "coño",
        "mierda",
        "carajo",
        "carajo",
        "puta",
        "puto",
        "hijueputa",
        "hijo de puta",
        "hp",
        "idiota",
        "imbecil",
        "imbécil",
        "estupido",
        "estúpido",
        "pendejo",
        "pendeja",
        "cabron",
        "cabrón",
        "malparido",
        "verga",
        "pinga",
        "joder",
        "jodete",
        "jódete",
        "fuck",
        "shit",
        "asshole",
        "bastardo",
        "culero",
        "maricon",
        "maricón",
    }
)

# Señales de intención bancaria / funcional (si aparecen junto a grosería, se procesa).
_FUNCTIONAL_SIGNALS = (
    "saldo",
    "balance",
    "cuenta",
    "tarjeta",
    "prestamo",
    "préstamo",
    "transfer",
    "movimiento",
    "cuota",
    "disponible",
    "limite",
    "límite",
    "certificado",
    "cdt",
    "deposito",
    "depósito",
    "reclam",
    "mision",
    "misión",
    "vision",
    "visión",
    "banco",
    "producto",
    "portafolio",
)


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    for a, b in (
        ("á", "a"),
        ("é", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        ("ü", "u"),
        ("ñ", "n"),
    ):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _profanity_set() -> frozenset[str]:
    extra = os.getenv("GENESIS_PROFANITY_EXTRA", "")
    items = set(_BASE_PROFANITY)
    for part in extra.split(","):
        p = part.strip().lower()
        if p:
            items.add(p)
            items.add(_norm(p))
    # también versiones normalizadas de la base
    for w in list(items):
        items.add(_norm(w))
    return frozenset(items)


@dataclass(frozen=True)
class ModerationResult:
    is_offensive: bool
    has_functional_intent: bool
    cleaned_text: str
    matched_terms: tuple[str, ...]

    @property
    def block_and_redirect(self) -> bool:
        """True si solo hay grosería sin pedido bancario usable."""
        return self.is_offensive and not self.has_functional_intent


_REDIRECT_MSG = (
    "Estoy aquí para ayudarte con tus consultas bancarias. "
    "Por favor indícame qué necesitas (saldo, productos, información del banco u otros servicios)."
)


def moderate_user_text(raw_text: str) -> ModerationResult:
    """Analiza el texto del usuario. No muta el original salvo cleaned_text."""
    original = (raw_text or "").strip()
    if not original:
        return ModerationResult(False, False, original, ())

    ql = original.lower()
    qn = _norm(original)
    terms = _profanity_set()
    matched: list[str] = []

    # Match por token y por frase (multi-palabra)
    tokens = set(qn.split())
    for term in terms:
        tn = _norm(term)
        if not tn:
            continue
        if " " in tn:
            if tn in qn:
                matched.append(term)
        elif tn in tokens:
            matched.append(term)

    is_off = bool(matched)
    has_func = any(s in ql or _norm(s) in qn for s in _FUNCTIONAL_SIGNALS)

    cleaned = original
    if is_off and has_func:
        # Quitar términos ofensivos para el resto del pipeline
        cleaned_n = qn
        for term in matched:
            cleaned_n = cleaned_n.replace(_norm(term), " ")
        cleaned_n = re.sub(r"\s+", " ", cleaned_n).strip()
        cleaned = cleaned_n or original

    return ModerationResult(
        is_offensive=is_off,
        has_functional_intent=has_func,
        cleaned_text=cleaned,
        matched_terms=tuple(dict.fromkeys(matched)),
    )


def apply_moderation_guardrail(
    snapshot: Any,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Fast-path: grosería sin intención → redirección neutral (NON_OPERATIONAL)."""
    result = moderate_user_text(raw_text)
    if not result.block_and_redirect:
        return None

    name = getattr(snapshot, "display_name", None) if snapshot is not None else None
    greeting = f"{name}, " if name else ""
    text = f"{greeting}{_REDIRECT_MSG}"
    return "NON_OPERATIONAL", [], text, None


def moderation_redirect_message(display_name: str | None = None) -> str:
    greeting = f"{display_name}, " if display_name else ""
    return f"{greeting}{_REDIRECT_MSG}"
