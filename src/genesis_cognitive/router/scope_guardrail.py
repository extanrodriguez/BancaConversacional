"""Alcance del asistente (ASSISTANT_SCOPE) — qué puede hacer la IA con el usuario logueado."""

from __future__ import annotations

from typing import Any


_SCOPE_SIGNALS = (
    "en que me puedes ayudar",
    "en qué me puedes ayudar",
    "en que puedes ayudarme",
    "en qué puedes ayudarme",
    "que puedes hacer",
    "qué puedes hacer",
    "que sabes hacer",
    "qué sabes hacer",
    "cuales son tus funciones",
    "cuáles son tus funciones",
    "que servicios tienes",
    "qué servicios tienes",
    "cual es tu alcance",
    "cuál es tu alcance",
    "que haces",
    "qué haces",
    "como me ayudas",
    "cómo me ayudas",
    "para que sirves",
    "para qué sirves",
    "ayuda disponible",
    "menu de opciones",
    "menú de opciones",
)


def is_assistant_scope_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t or len(t) > 120:
        return False
    # Normalizar signos
    for ch in "¿?¡!.,;:":
        t = t.replace(ch, "")
    t = " ".join(t.split())
    return any(s in t for s in _SCOPE_SIGNALS)


def build_scope_response(snapshot: Any) -> str:
    """Lista capacidades según portafolio del snapshot (usuario autenticado)."""
    name = getattr(snapshot, "display_name", None) if snapshot else None
    greeting = f"{name}, " if name else ""

    products = tuple(getattr(snapshot, "products", ()) or ()) if snapshot else ()
    loans = tuple(getattr(snapshot, "loans", ()) or ()) if snapshot else ()

    active = [p for p in products if str(getattr(p, "status", "")).lower() in ("active", "1", "3", "activo")]
    if not active and products:
        active = list(products)

    types = {str(getattr(p, "product_type", "")).upper() for p in active}
    has_accounts = bool(types & {"SAVINGS", "CHECKING", "PAYROLL"})
    has_cards = "CREDIT_CARD" in types
    has_dap = "TERM_DEPOSIT" in types
    has_loans = "LOAN" in types or bool(loans)

    bullets: list[str] = []
    if has_accounts:
        bullets.append("Consultar saldos y movimientos de tus cuentas de ahorro o corriente")
    if has_cards:
        bullets.append("Ver detalle de tus tarjetas de crédito (límite, adeudo, pago mínimo)")
    if has_loans:
        bullets.append("Consultar información de tus préstamos")
    if has_dap:
        bullets.append("Consultar tus certificados de depósito / DAP")
    if active:
        bullets.append("Ver el resumen de tus productos activos")
    else:
        bullets.append("Consultar información de productos asociados a tu sesión")

    bullets.extend(
        [
            "Información general del banco (misión, visión, definiciones, requisitos)",
            "Orientarte sobre procesos como reclamaciones (canales y pasos)",
        ]
    )

    lines = [
        f"{greeting}hoy puedo ayudarte con lo siguiente:",
        "",
        *[f"• {b}" for b in bullets],
        "",
        "Aún no realizo transferencias, pagos ni otras operaciones. "
        "¿Qué deseas consultar?",
    ]
    return "\n".join(lines)


def apply_scope_guardrail(
    snapshot: Any,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    if snapshot is None or not is_assistant_scope_question(raw_text):
        return None
    text = build_scope_response(snapshot)
    action = {
        "sequence": 1,
        "intent_id": "ASSISTANT_SCOPE",
        "capability_candidate": "ASSISTANT_SCOPE",
        "selected_route": "NON_OPERATIONAL",
        "detected_entities": {
            "account_ref": None,
            "source_account_ref": None,
            "destination_account_ref": None,
            "amount": None,
            "currency": None,
            "knowledge_topic": "ALCANCE_ASISTENTE",
        },
        "missing_requirements": [],
        "depends_on": [],
        "confidence": 1.0,
    }
    return "VALID_CONTRACT", [action], text, None
