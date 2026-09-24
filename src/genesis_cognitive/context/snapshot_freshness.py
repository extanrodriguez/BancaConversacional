"""Frescura del snapshot bancario para respuestas cognitivas.

Política configurable (NO es umbral bancario oficial):
  GENESIS_SNAPSHOT_STALE_AFTER_S — segundos tras los cuales el dato se
  considera vencido para presentación. Si no está definido, no se aplica
  vencimiento por edad (solo se trata el caso 'unknown').

Valor de prueba documentado en tests: 120 segundos.
No realiza llamadas al Core.
"""

from __future__ import annotations

import os
import time
from typing import Any, Literal

FreshnessClass = Literal["fresh", "stale", "unknown"]

# Disclaimer sin afirmar actualidad
_STALE_NOTE = (
    " Nota: este dato del portafolio tiene antigüedad de {age:.0f}s "
    "según la política de prueba ({ttl:.0f}s); no lo confirmo como vigente."
)
_UNKNOWN_NOTE = (
    " Nota: la fecha de origen del dato bancario es desconocida; "
    "no lo presento como actualizado."
)


def stale_after_s() -> float | None:
    raw = (os.getenv("GENESIS_SNAPSHOT_STALE_AFTER_S") or "").strip()
    if not raw or raw.lower() in ("0", "none", "off", "false"):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def age_from_session(session: Any | None) -> float | None:
    """Edad en segundos desde source_fetched_at de la sesión, si existe."""
    if session is None:
        return None
    fetched = getattr(session, "snapshot_source_fetched_at", None)
    if fetched is None:
        return None
    try:
        return max(0.0, time.time() - float(fetched))
    except (TypeError, ValueError):
        return None


def classify_freshness(age_s: float | None, *, ttl_s: float | None = None) -> FreshnessClass:
    if age_s is None:
        return "unknown"
    policy = stale_after_s() if ttl_s is None else ttl_s
    if policy is None:
        return "fresh"
    if age_s > policy:
        return "stale"
    return "fresh"


def annotate_portfolio_amount_text(
    text: str,
    *,
    session: Any | None = None,
    age_s: float | None = None,
    ttl_s: float | None = None,
) -> str:
    """Evita presentar montos vencidos como actuales.

    Sin política TTL (GENESIS_SNAPSHOT_STALE_AFTER_S), no se añade nota:
    en lab/QA el dato del snapshot es el contrato vigente y la nota de
    «fecha desconocida» confunde al cliente aunque el monto sea correcto.
    """
    body = (text or "").rstrip()
    if not body:
        return body
    policy = stale_after_s() if ttl_s is None else ttl_s
    # Sin TTL configurado: no anotar (ni unknown ni stale)
    if policy is None and ttl_s is None:
        return body
    resolved_age = age_s if age_s is not None else age_from_session(session)
    kind = classify_freshness(resolved_age, ttl_s=ttl_s)
    if kind == "fresh":
        return body
    # Evitar dobles notas
    if "no lo confirmo como vigente" in body or "fecha de origen del dato" in body:
        return body
    if kind == "stale":
        return body + _STALE_NOTE.format(age=resolved_age or 0.0, ttl=policy or 0.0)
    # unknown solo si hay política TTL activa (entorno que exige frescura)
    if policy is None:
        return body
    return body + _UNKNOWN_NOTE
