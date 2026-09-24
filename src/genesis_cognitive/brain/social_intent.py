"""Detección de presencia / correcciones / small-talk (IA bancaria conversacional)."""

from __future__ import annotations

import re
import unicodedata


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = "".join(
        c for c in unicodedata.normalize("NFD", t)
        if unicodedata.category(c) != "Mn"
    )
    t = re.sub(r"[¿?¡!.,;:]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


_PRESENCE = (
    "estas ahi",
    "estas alli",
    "sigues ahi",
    "sigue ahi",
    "aun estas",
    "todavia estas",
    "me escuchas",
    "me oyes",
    "hay alguien",
    "estas online",
    "estas conectado",
    "buenas",
)

_CORRECTION = (
    "no te pregunt",
    "no te estoy pregunt",
    "no estoy pregunt",
    "no te hable",
    "no te hable de",
    "no dije",
    "no era eso",
    "no es eso",
    "eso no",
    "te equivoc",
    "no quiero eso",
    "no es lo que",
    "no te pedi",
    "malentendido",
    "no es sobre",
    "no era sobre",
)

_THANKS = (
    "gracias",
    "muchas gracias",
    "mil gracias",
    "te agradezco",
    "perfecto gracias",
)

_ACK = (
    "si",
    "ok",
    "okay",
    "vale",
    "listo",
    "entendido",
    "de acuerdo",
    "claro",
    "perfecto",
    "excelente",
    "dale",
)

_BANK = (
    "saldo", "tarjeta", "prestamo", "cuota", "certificado", "deposito",
    "cuenta", "dap", "cdt", "transfer", "pago", "mora", "tasa", "capital",
    "disponible", "limite", "corte", "adeud", "debito", "credito",
    "ahorro", "nomina", "reclam", "banco", "bsc",
)


def classify_social(question: str) -> tuple[str, float] | None:
    """Devuelve (field, confidence) o None si no es social.

    field: presence | correction | thanks | ack | smalltalk
    """
    q = _norm(question)
    if not q or len(q) > 120:
        return None

    # Correcciones: prioridad aunque mencionen producto ("no te pregunté por depósitos")
    if any(s in q for s in _CORRECTION):
        return "correction", 0.95

    if any(q == s or q.startswith(s + " ") or q.endswith(" " + s) or s in q for s in _PRESENCE):
        if len(q) <= 40:
            return "presence", 0.95

    if any(q == s or q.startswith(s) for s in _THANKS) and not any(b in q for b in _BANK):
        return "thanks", 0.9

    if q in _ACK or (len(q) <= 18 and any(q == s for s in _ACK)):
        return "ack", 0.85

    # Frase corta social sin tema bancario
    if len(q) <= 45 and not any(b in q for b in _BANK):
        # Evitar dígitos de producto / opciones numéricas solas
        if re.fullmatch(r"\d{1,2}", q):
            return None
        if re.search(r"\d{4,}", q):
            return None
        # Small talk típico
        if any(
            s in q
            for s in (
                "como estas", "que tal", "todo bien", "buenas noches",
                "hasta luego", "chao", "adios", "nos vemos", "quien eres",
                "que puedes hacer", "en que me ayudas", "me puedes ayudar",
            )
        ):
            return "smalltalk", 0.9
        # Interjecciones / check-ins muy cortos
        if len(q.split()) <= 5 and "?" not in (question or "") and q in (
            "hola", "hey", "ey", "oye", "mira", "disculpa", "perdon", "perdón",
        ):
            return "smalltalk", 0.8

    return None
