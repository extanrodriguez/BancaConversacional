"""Foco de producto en sesión + gate personal vs conocimiento.

last_resolved = deíxis inmediata (no se pisa con turnos de KB).
product_focus = memoria del último producto personal; sobrevive FAQ/RAG
para reanudar ("y la tasa?" tras hablar de otro tema).

La tasa/cuota/mora NUNCA las inventa el RAG: el gate solo clasifica
personal vs definición; el dato sale del snapshot.
"""

from __future__ import annotations

from typing import Any

from genesis_cognitive.context.reactive_store import ProductFocus

_PERSONAL_FOCUS_INTENTS = {
    "LOAN_DETAIL_READ": "LOAN",
    "ACCOUNT_BALANCE_READ": "ACCOUNT",
    "ACCOUNT_MOVEMENTS_READ": "ACCOUNT",
    "CREDIT_CARD_DETAIL_READ": "CARD",
    "TERM_DEPOSIT_DETAIL_READ": "TERM_DEPOSIT",
}

_LOAN_LIST_SIGNALS = (
    "mis prestamos",
    "mis préstamos",
    "todos mis prestamo",
    "todos mis préstamo",
    "listado de prestamo",
    "listado de préstamo",
    "que prestamos tengo",
    "qué préstamos tengo",
    "cuales prestamos",
    "cuáles préstamos",
    "informacion sobre mis prestamo",
    "información sobre mis préstamo",
    "dame informacion sobre mis prestamo",
    "dame información sobre mis préstamo",
)


def kind_for_intent(intent_id: str | None) -> str | None:
    if not intent_id:
        return None
    return _PERSONAL_FOCUS_INTENTS.get(intent_id)


def is_knowledge_intent(intent_id: str | None) -> bool:
    return (intent_id or "") in (
        "BUSINESS_KNOWLEDGE_QUERY",
        "NON_OPERATIONAL",
        "UNSUPPORTED",
    )


def should_update_last_resolved(
    intent_id: str | None,
    account_ref: str | None,
    session: Any | None = None,
    question: str = "",
) -> bool:
    """No pisar el producto activo con turnos de conocimiento / sin ref."""
    if is_knowledge_intent(intent_id):
        return False
    if not account_ref:
        return False
    if kind_for_intent(intent_id) is None:
        return False
    # No dejar que un saldo de cuenta accidental pise un DAP/préstamo/TC en foco
    # (p. ej. follow-up "Y del 05809?" mal resuelto como ahorro).
    if intent_id in ("ACCOUNT_BALANCE_READ", "ACCOUNT_MOVEMENTS_READ") and session is not None:
        focus = getattr(session, "product_focus", None)
        if focus is not None and getattr(focus, "kind", None) in ("LOAN", "TERM_DEPOSIT", "CARD"):
            q = (question or "").lower()
            explicit_account = any(
                s in q
                for s in (
                    "cuenta",
                    "ahorro",
                    "ahorros",
                    "corriente",
                    "nomina",
                    "nómina",
                    "saldo de mi",
                    "mi saldo",
                    "balance de mi",
                )
            )
            if not explicit_account:
                return False
    return True


def remember_product_focus(
    session: Any,
    intent_id: str | None,
    account_ref: str | None,
    question: str = "",
) -> None:
    """Persiste foco de producto personal (cuenta / préstamo / DAP / tarjeta)."""
    import re
    import time

    kind = kind_for_intent(intent_id)
    if kind not in ("ACCOUNT", "LOAN", "TERM_DEPOSIT", "CARD") or not account_ref:
        return
    existing = getattr(session, "product_focus", None)
    oq = (question or "")[:200]
    # Follow-up solo dígitos: conservar la pregunta de campo (tasa/vence/…)
    if (
        existing is not None
        and getattr(existing, "kind", None) == kind
        and getattr(existing, "original_question", None)
        and re.match(
            r"(?is)^\s*(?:y\s+)?(?:del?|el|la|de\s+la)?\s*[#.]?\s*\d{3,8}\s*\??\s*$",
            question or "",
        )
    ):
        oq = str(existing.original_question)[:200]
    session.product_focus = ProductFocus(
        kind=kind,
        product_id=account_ref,
        intent_id=intent_id or "",
        original_question=oq,
        updated_at=time.time(),
    )


def account_ref_from_session(session: Any | None) -> str | None:
    """Ref de cuenta usable para deíxis / reanudación tras KB."""
    if session is None:
        return None
    lr = getattr(session, "last_resolved", None)
    if lr is not None and getattr(lr, "intent_id", None) in (
        "ACCOUNT_BALANCE_READ",
        "ACCOUNT_MOVEMENTS_READ",
    ):
        ref = getattr(lr, "account_ref", None)
        if ref:
            return str(ref)
    focus = getattr(session, "product_focus", None)
    if focus is not None and getattr(focus, "kind", None) == "ACCOUNT":
        ref = getattr(focus, "product_id", None)
        if ref:
            return str(ref)
    return None


def loan_ref_from_session(session: Any | None) -> str | None:
    """Ref de préstamo usable para deíxis / reanudación."""
    if session is None:
        return None
    lr = getattr(session, "last_resolved", None)
    if lr is not None and getattr(lr, "intent_id", None) == "LOAN_DETAIL_READ":
        ref = getattr(lr, "account_ref", None)
        if ref:
            return str(ref)
    focus = getattr(session, "product_focus", None)
    if focus is not None and getattr(focus, "kind", None) == "LOAN":
        ref = getattr(focus, "product_id", None)
        if ref:
            return str(ref)
    return None


def dap_ref_from_session(session: Any | None) -> str | None:
    """Ref de certificado/DAP usable para deíxis / reanudación."""
    if session is None:
        return None
    lr = getattr(session, "last_resolved", None)
    if lr is not None and getattr(lr, "intent_id", None) == "TERM_DEPOSIT_DETAIL_READ":
        ref = getattr(lr, "account_ref", None)
        if ref:
            return str(ref)
    focus = getattr(session, "product_focus", None)
    if focus is not None and getattr(focus, "kind", None) == "TERM_DEPOSIT":
        ref = getattr(focus, "product_id", None)
        if ref:
            return str(ref)
    return None


def focused_field_question(session: Any | None) -> str:
    """Última pregunta de campo (tasa/vence/…) para reanudar deíxis."""
    if session is None:
        return ""
    lr = getattr(session, "last_resolved", None)
    if lr is not None and getattr(lr, "original_question", None):
        return str(lr.original_question)
    focus = getattr(session, "product_focus", None)
    if focus is not None and getattr(focus, "original_question", None):
        return str(focus.original_question)
    return ""


def looks_like_product_option_selection(text: str) -> bool:
    """True si el mensaje parece elegir una card/opción APK (no una pregunta nueva)."""
    import re

    t = (text or "").strip().lower()
    if not t or len(t) > 140:
        return False
    # "Préstamo ...27615" / "Tarjeta ···6374" / máscaras APK
    if re.search(r"(···|\.{2,}|…|\*{3,}|••••)\s*\d{3,}", t):
        return True
    # Solo id / "el de 7615"
    if re.fullmatch(r"(?:el\s+(?:de\s+)?|la\s+(?:de\s+)?)?\d{4,8}\s*\??", t):
        return True
    # Ids APK: DEPOSITO_PLAZO_5511 / PRESTAMO_7615 / TARJETA_6374
    if re.search(
        r"\b(deposito_plazo|depósito_plazo|prestamo|préstamo|tarjeta|cuenta)[_\s.-]*\d{3,}\b",
        t,
    ):
        return True
    # "préstamo 7615" / "certificado 5511" sin verbo de campo
    if re.search(
        r"(?:prestamo|préstamo|tarjeta|cuenta|certificado|deposito|depósito)[_\s.-]*\d{4,}",
        t,
    ) and not any(
        s in t
        for s in (
            "fecha", "cuanto", "cuánto", "tasa", "saldo", "cuando", "cuándo",
            "cual es", "cuál es", "debo", "limite", "límite", "capital", "mora",
            "detalle", "info", "deuda", "adeud",
        )
    ):
        return True
    return False


def pending_field_question_for_selection(session: Any | None, selection_text: str) -> str:
    """Si hay pending esperando producto y el texto es una card, devolver la pregunta de campo."""
    if session is None or not looks_like_product_option_selection(selection_text):
        return ""
    pending = getattr(session, "pending_action", None)
    if pending is None:
        return ""
    missing = getattr(pending, "missing_requirements", None) or []
    if "account_ref" not in missing:
        return ""
    ents = getattr(pending, "detected_entities", None) or {}
    if ents.get("account_ref"):
        return ""
    oq = (getattr(pending, "original_question", None) or "").strip()
    from genesis_cognitive.context.query_spec import query_question

    return query_question(getattr(pending, "query_spec", None), oq) or oq


def resolve_original_question_for_persist(session: Any | None, question: str) -> str:
    """En follow-ups cortos de dígitos, conservar la pregunta de campo previa."""
    import re

    q = question or ""
    if not re.match(
        r"(?is)^\s*(?:y\s+)?(?:del?|el|la|de\s+la)?\s*[#.]?\s*\d{3,8}\s*\??\s*$",
        q,
    ):
        return q
    prev = focused_field_question(session)
    return prev or q


def is_loan_list_question(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in _LOAN_LIST_SIGNALS)


def prefer_personal_loan_over_knowledge(text: str, session: Any | None) -> bool:
    """True si la intención es dato del préstamo en foco, no glosario FAQ."""
    from genesis_cognitive.router.snapshot_guardrails import (
        _is_loan_definition_question,
        is_loan_deictic_field_question,
        is_loan_field_question,
    )

    t = (text or "").strip()
    if not t:
        return False
    if _is_loan_definition_question(t):
        return False
    if is_loan_list_question(t):
        return False
    if not loan_ref_from_session(session):
        return False
    if is_loan_field_question(t, allow_deictic_fields=True):
        return True
    if is_loan_deictic_field_question(t):
        return True
    return False


def resolve_loan_field_intent(
    text: str,
    session: Any | None,
) -> dict[str, Any] | None:
    """Gate: PERSONAL_LOAN (snapshot) vs KNOWLEDGE (FAQ/RAG). No inventa montos."""
    if prefer_personal_loan_over_knowledge(text, session):
        return {
            "route": "PERSONAL_LOAN",
            "product_id": loan_ref_from_session(session),
            "reason": "session_loan_focus_or_resolved",
        }

    from genesis_cognitive.router.snapshot_guardrails import (
        _is_loan_definition_question,
        is_loan_field_question,
    )

    if _is_loan_definition_question(text or ""):
        return {"route": "KNOWLEDGE", "product_id": None, "reason": "definition"}
    if is_loan_field_question(text or ""):
        return {
            "route": "PERSONAL_LOAN",
            "product_id": loan_ref_from_session(session),
            "reason": "explicit_loan_field",
        }
    return None
