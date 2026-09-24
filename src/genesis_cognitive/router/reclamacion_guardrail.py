"""Flujo de reclamaciones — overview KB + canal opcional; no atrapar otros intents."""

from __future__ import annotations

import re
from typing import Any

_RECLAMACION_SIGNALS = (
    "reclamacion",
    "reclamación",
    "reclamar",
    "reclamo",
    "queja",
    "poner una reclamacion",
    "poner una reclamación",
    "proceso de reclam",
    "proceso para una reclam",
    "como hago una reclam",
    "cómo hago una reclam",
    "donde puedo reclamar",
    "dónde puedo reclamar",
)

_CHANNEL_CONTACT = ("contacto", "809", "telefono", "teléfono", "llamar", "call center", "centro de contacto")
_CHANNEL_BRANCH = ("sucursal", "centro de negocio", "negocios", "oficina", "presencial", "visitar")
_CHANNEL_ONLINE = ("en linea", "en línea", "online", "app", "bsc en linea", "bsc en línea", "internet")

# Respuestas cortas típicas a la clarificación de canal
_CHANNEL_REPLY_HINTS = (
    "contacto", "telefono", "teléfono", "llamar", "809",
    "sucursal", "oficina", "presencial", "negocios", "negocio",
    "linea", "línea", "online", "app", "internet", "bsc",
    "todos", "cualquiera", "el primero", "el segundo", "el tercero",
    "1", "2", "3",
)

_CLARIFY_QUESTION = (
    "Puedes realizar tu reclamación por varios canales. "
    "¿Cuál prefieres?\n"
    "• Centro de Contacto (809.726.1000)\n"
    "• Centro de Negocios (presencial)\n"
    "• BSC en Línea"
)

_CONTACTS = (
    "• Centro de Contacto: 809.726.1000\n"
    "• Correo para documentos: serviciobancanet@bsc.com.do\n"
    "• Protección al usuario: proteccionalusuariobsc@bsc.com.do\n"
    "• Web: https://bsc.com.do/"
)

_ANSWERS = {
    "contact_center": (
        "Puedes abrir tu reclamación llamando al Centro de Contacto: **809.726.1000**.\n\n"
        "Una vez registrada, recibirás en el correo asociado a tu cuenta el Formulario Único "
        "de Reclamación con el número y detalle de tu caso.\n\n"
        f"Canales de contacto:\n{_CONTACTS}\n\n"
        "¿Deseas que te indique también la documentación típica según el tipo de reclamación?"
    ),
    "branch": (
        "Puedes presentar tu reclamación visitando el área de Servicios del Centro de Negocios "
        "de tu preferencia.\n\n"
        f"Canales y ubicaciones:\n{_CONTACTS}\n\n"
        "Al registrarla, recibirás el Formulario Único de Reclamación por correo con el número de caso.\n\n"
        "¿Deseas conocer la documentación que suelen solicitar?"
    ),
    "online": (
        "Puedes gestionar tu reclamación a través de **BSC en Línea**.\n\n"
        "Al registrarla, recibirás automáticamente en tu correo el Formulario Único de Reclamación "
        "con el número y los detalles del caso.\n\n"
        f"Canales de apoyo:\n{_CONTACTS}\n\n"
        "¿Quieres que te detalle los documentos de soporte según el tipo de caso?"
    ),
    "overview": (
        "Puedes realizar tu reclamación a través de estos canales:\n\n"
        f"{_CONTACTS}\n"
        "• Centros de Negocios BSC (área de Servicios)\n"
        "• BSC en Línea\n\n"
        "Al registrar tu caso recibirás el Formulario Único de Reclamación por correo.\n\n"
        "Indícame el canal que prefieres si quieres el detalle paso a paso "
        "(Centro de Contacto, Centro de Negocios o BSC en Línea)."
    ),
}


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    return t


def is_reclamacion_question(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    return any(_norm(s) in t for s in _RECLAMACION_SIGNALS)


_PERSONAL_PORTFOLIO_SIGNALS = (
    "mis productos",
    "mi cuenta",
    "mi prestamo",
    "mi prestamos",
    "mi tarjeta",
    "mis cuentas",
    "mis prestamos",
    "mis tarjetas",
    "mis saldos",
    "dame todos mis",
    "dame mis",
    "dime mis",
    "portafolio",
    "que tengo",
    "qué tengo",
)


def detect_reclamacion_channel(text: str) -> str | None:
    t = _norm(text)
    # "dame todos mis productos" no es elección de canal (evita atrapar por "todos")
    if any(s in t for s in _PERSONAL_PORTFOLIO_SIGNALS):
        return None
    if any(_norm(s) in t for s in _CHANNEL_CONTACT):
        return "contact_center"
    if any(_norm(s) in t for s in _CHANNEL_BRANCH):
        return "branch"
    if any(_norm(s) in t for s in _CHANNEL_ONLINE):
        return "online"
    if "todos los canales" in t or "proceso completo" in t or "documentacion" in t or "documentación" in t:
        return "overview"
    # Solo respuestas cortas de canal: "todos", "todas", "cualquiera" — no frases con productos
    toks = t.split()
    if t in {"todos", "todas", "cualquiera", "todos los", "todas las"}:
        return "overview"
    if len(toks) <= 3 and toks and toks[0] in {"todos", "todas"} and not any(
        x in t for x in ("producto", "cuenta", "prestamo", "tarjeta", "saldo", "portafolio")
    ):
        return "overview"
    return None


def _looks_like_channel_reply(text: str) -> bool:
    """Respuesta corta plausible a la pregunta de canal (no un cambio de tema)."""
    t = _norm(text)
    if not t:
        return False
    if any(s in t for s in _PERSONAL_PORTFOLIO_SIGNALS):
        return False
    toks = t.split()
    if len(toks) > 8:
        return False
    if is_reclamacion_question(text):
        return True
    return any(_norm(h) in t for h in _CHANNEL_REPLY_HINTS)


def is_topic_switch_from_reclamacion(text: str) -> bool:
    """El usuario cambió de tema mientras había clarificación de canal pendiente."""
    t = _norm(text)
    if not t:
        return False
    if is_reclamacion_question(text):
        return False
    # Señales claras de otro intent primero (antes de heurísticas de canal como "todos")
    switches = (
        "producto", "productos", "cuenta", "cuentas", "prestamo", "préstamo", "prestamos",
        "préstamos", "tarjeta", "tarjetas", "saldo", "listado", "lista", "contratar",
        "solicitar", "adquirir", "mision", "misión", "vision", "visión", "transfer",
        "movimiento", "certificado", "deposito", "depósito", "mis productos", "mi cuenta",
        "mi prestamo", "mi préstamo", "informacion de", "información de", "cuentame",
        "cuéntame", "hablame", "háblame", "que es", "qué es", "hola", "buenos", "gracias",
        "cancelar", "banco", "bsc", "cual es mi", "cuál es mi", "dame mis", "dime mis",
        "dame todos mis", "cuanto debo", "cuánto debo", "portafolio", "que tengo", "qué tengo",
    )
    if any(s in t for s in switches) or any(s in t for s in _PERSONAL_PORTFOLIO_SIGNALS):
        return True
    if len(t.split()) >= 6:
        return True
    if detect_reclamacion_channel(text):
        return False
    if _looks_like_channel_reply(text):
        return False
    return False


def _action(topic: str, confidence: float = 0.95) -> dict:
    return {
        "sequence": 1,
        "intent_id": "BUSINESS_KNOWLEDGE_QUERY",
        "capability_candidate": "BUSINESS_KNOWLEDGE",
        "selected_route": "BUSINESS_RAG",
        "detected_entities": {
            "account_ref": None,
            "source_account_ref": None,
            "destination_account_ref": None,
            "amount": None,
            "currency": None,
            "knowledge_topic": topic,
        },
        "missing_requirements": [],
        "depends_on": [],
        "confidence": confidence,
    }


def _trim_kb_answer_for_mobile(ans: str, *, max_chars: int = 2200) -> str:
    """Acota longitud sin cortar a mitad de frase ni dejar secciones rotas.

    Preferencia: párrafo completo → oración completa. Si el recorte caería
    dentro de un bloque "Importante:" incompleto, se elimina ese bloque.
    """
    text = (ans or "").strip()
    if len(text) <= max_chars:
        return text

    window = text[:max_chars]
    # 1) Último párrafo completo
    cut = window.rfind("\n\n")
    if cut >= int(max_chars * 0.45):
        trimmed = window[:cut].rstrip()
    else:
        # 2) Última oración que termine en . ! ?
        m = None
        for match in re.finditer(r"[.!?…](?=\s|$)", window):
            m = match
        if m and m.end() >= int(max_chars * 0.45):
            trimmed = window[: m.end()].rstrip()
        else:
            # 3) Último espacio (evitar palabra a medias), sin ellipsis engañosa
            sp = window.rfind(" ")
            trimmed = window[:sp].rstrip() if sp > int(max_chars * 0.45) else window.rstrip()

    # Si quedó un encabezado "Importante:" sin cuerpo útil, quitarlo
    low = trimmed.lower()
    for marker in ("\n\nimportante:\n", "\nimportante:\n", "\n\nimportante:", "\nimportante:"):
        idx = low.rfind(marker)
        if idx >= 0:
            after = trimmed[idx + len(marker) :].strip()
            # Cuerpo demasiado corto o sin punto final → sección incompleta
            if len(after) < 40 or not re.search(r"[.!?]$", after):
                trimmed = trimmed[:idx].rstrip()
            break

    # Nunca devolver corte tipo "Los documentos deben…"
    trimmed = re.sub(r"(?:\s*…|\s*\.\.\.)\s*$", "", trimmed).rstrip()
    if trimmed and trimmed[-1] not in ".!?:;":
        # Si no cierra frase, retroceder a la última oración completa
        m = None
        for match in re.finditer(r"[.!?…](?=\s|$)", trimmed):
            m = match
        if m and m.end() >= int(len(trimmed) * 0.5):
            trimmed = trimmed[: m.end()].rstrip()

    return trimmed or text[:max_chars].rstrip()


def _kb_overview_answer() -> str | None:
    """Preferir texto grounded del FAQ/corpus si está disponible."""
    try:
        from genesis_cognitive.rag.kb_intent_resolver import resolve_knowledge_intent

        hit = resolve_knowledge_intent(
            "proceso de reclamaciones apertura de reclamaciones canales",
            min_score=0.35,
        )
        if not hit or not hit.get("answer"):
            return None
        topic = _norm(hit.get("topic") or "")
        if "reclam" not in topic and "reclam" not in _norm(hit.get("answer") or "")[:200]:
            return None
        ans = str(hit["answer"]).strip()
        if len(ans) < 80:
            return None
        return _trim_kb_answer_for_mobile(ans)
    except Exception:
        return None


def apply_reclamacion_guardrail(
    snapshot: Any,
    raw_text: str,
    *,
    pending_topic: str | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """
    - Primera mención de proceso → overview KB (VALID) + invitación a elegir canal
    - Pending canal + respuesta de canal → detalle
    - Pending + cambio de tema → None (libera el loop)
    """
    q = (raw_text or "").strip()
    if not q:
        return None

    continuing = (pending_topic or "") == "RECLAMACION_CHANNEL"
    name = getattr(snapshot, "display_name", None) if snapshot is not None else None
    greeting = f"{name}, " if name else ""

    if continuing:
        # Nueva pregunta explícita de proceso → reset y overview KB completo
        if is_reclamacion_question(q) and detect_reclamacion_channel(q) is None:
            kb = _kb_overview_answer()
            body = kb or _ANSWERS["overview"]
            if "cuál prefieres" not in body.lower() and "cual prefieres" not in body.lower():
                body = (
                    f"{body.rstrip()}\n\n"
                    "Si quieres el detalle paso a paso, indícame el canal: "
                    "Centro de Contacto (809.726.1000), Centro de Negocios o BSC en Línea."
                )
            return "VALID_CONTRACT", [_action("RECLAMACION_OVERVIEW", 0.92)], f"{greeting}{body}", None
        # Cambio de tema: soltar pending y dejar que otros guardrails respondan
        if is_topic_switch_from_reclamacion(q):
            return None
        channel = detect_reclamacion_channel(q)
        if channel:
            body = _ANSWERS.get(channel, _ANSWERS["overview"])
            return "VALID_CONTRACT", [_action(f"RECLAMACION_{channel.upper()}")], f"{greeting}{body}", None
        if _looks_like_channel_reply(q):
            return (
                "CLARIFICATION_REQUIRED",
                [_action("RECLAMACION_CHANNEL", 0.7)],
                f"{greeting}No identifiqué el canal. {_CLARIFY_QUESTION}",
                None,
            )
        # Mensaje ambiguo corto sin señales → no atrapar eternamente
        return None

    if not is_reclamacion_question(q):
        return None

    channel = detect_reclamacion_channel(q)
    if channel:
        body = _ANSWERS.get(channel, _ANSWERS["overview"])
        return "VALID_CONTRACT", [_action(f"RECLAMACION_{channel.upper()}")], f"{greeting}{body}", None

    # Primera vez: entregar proceso/overview desde KB (no solo clarificar en vacío)
    kb = _kb_overview_answer()
    body = kb or _ANSWERS["overview"]
    # Si el usuario solo pregunta el proceso, respondemos completo sin forzar pending sticky.
    # Añadimos oferta de canal al final si el texto KB no la trae.
    if "cuál prefieres" not in body.lower() and "cual prefieres" not in body.lower():
        body = (
            f"{body.rstrip()}\n\n"
            "Si quieres el detalle paso a paso, indícame el canal: "
            "Centro de Contacto (809.726.1000), Centro de Negocios o BSC en Línea."
        )
    return "VALID_CONTRACT", [_action("RECLAMACION_OVERVIEW", 0.9)], f"{greeting}{body}", None
