"""Resolución de continuidad conversacional (capa cognitiva).

Reutiliza PendingAction, QuerySpec, ProductFocus y last_resolved.
No crea una memoria paralela ni toca el orquestador externo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot
from genesis_cognitive.context.product_display import filter_active_by_type
from genesis_cognitive.context.query_spec import query_question

_ACCOUNT_TYPES = ("SAVINGS", "CHECKING", "PAYROLL")
_USD = ("dolares", "dólares", "usd", "us$", "dollar")
_DOP = ("pesos", "dop", "rd$", "peso dominicano")
_OTHER_CCY = ("euros", "euro", "eur", "libras", "gbp", "cad", "mxn", "pesos mexicanos")
_ORDINAL = {
    1: ("primera", "primero", "1ra", "1er", "la 1", "el 1", "opcion 1", "opción 1", "la una"),
    2: ("segunda", "segundo", "2da", "2do", "la 2", "el 2", "opcion 2", "opción 2"),
    3: ("tercera", "tercero", "3ra", "3er", "la 3", "el 3", "opcion 3", "opción 3"),
}

_FIELD_TO_PACKET = {
    "available_balance": "available",
    "available": "available",
    "balance": "balance",
    "movements": "transactions",
    "transactions": "transactions",
    "detail": "detail",
}


@dataclass(frozen=True)
class ContinuityResolution:
    """Producto y campo resueltos para un follow-up / selección pendiente."""

    product_id: str
    product_kind: str  # account | credit_card | loan | term_deposit
    field: str
    intent_id: str
    reason: str
    original_question: str = ""
    ambiguous: bool = False
    missing: bool = False
    candidates: tuple[str, ...] = ()


def _currency_from_text(text: str) -> str | None:
    t = (text or "").lower()
    if any(s in t for s in _USD):
        return "USD"
    if any(s in t for s in _DOP):
        return "DOP"
    return None


def _mentions_unsupported_currency(text: str) -> bool:
    t = (text or "").lower()
    if _currency_from_text(t):
        return False
    return any(s in t for s in _OTHER_CCY)


def _ordinal_index(text: str) -> int | None:
    t = (text or "").strip().lower()
    t = re.sub(r"[¿?¡!.,;:]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for idx, signals in _ORDINAL.items():
        if any(s == t or s in t for s in signals):
            return idx
    if re.fullmatch(r"[123]", t):
        return int(t)
    return None


def _is_deictic_same(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(
        re.search(
            r"\b(esa cuenta|esa|ese|ese producto|la misma|el mismo|esa misma)\b",
            t,
        )
    )


def _is_other_ref(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(
        s in t
        for s in (
            "la otra", "el otro", "la demas", "la demás", "la restante",
            "consultar la otra", "consultar el otro", "ahora la otra", "ahora el otro",
        )
    )


def _is_explicit_switch(text: str) -> bool:
    t = (text or "").lower()
    return any(
        s in t
        for s in (
            "no,",
            "no ahora",
            "ahora la",
            "ahora el",
            "mejor la",
            "mejor el",
            "cambia a",
            "cambiame a",
            "cámbiame a",
            "en realidad la",
            "en realidad el",
        )
    ) or (t.startswith("no ") and _currency_from_text(t) is not None)


def _kind_for_product(product: Any) -> str:
    ptype = str(getattr(product, "product_type", "") or "")
    if ptype in _ACCOUNT_TYPES:
        return "account"
    if ptype == "CREDIT_CARD":
        return "credit_card"
    if ptype == "LOAN":
        return "loan"
    if ptype == "TERM_DEPOSIT":
        return "term_deposit"
    return "account"


def _intent_for_kind(kind: str) -> str:
    return {
        "account": "ACCOUNT_BALANCE_READ",
        "credit_card": "CREDIT_CARD_DETAIL_READ",
        "loan": "LOAN_DETAIL_READ",
        "term_deposit": "TERM_DEPOSIT_DETAIL_READ",
    }.get(kind, "ACCOUNT_BALANCE_READ")


def _packet_field_from_spec(spec: dict[str, Any] | None, fallback: str = "balance") -> str:
    raw = str((spec or {}).get("field") or fallback)
    return _FIELD_TO_PACKET.get(raw, raw if raw in _FIELD_TO_PACKET.values() else fallback)


def _field_from_question(question: str, default: str = "balance") -> str:
    q = (question or "").lower()
    if any(s in q for s in ("movimiento", "transaccion", "transacción")):
        return "transactions"
    if any(s in q for s in ("saldo actual", "balance actual", "saldo contable", "ledger")):
        return "balance"
    if "disponible" in q and "saldo actual" not in q:
        return "available"
    if any(s in q for s in ("saldo", "balance", "cuanto tengo", "cuánto tengo")):
        return "balance"
    return default


def _candidate_pool(
    snapshot: CustomerContextSnapshot,
    session: Any | None,
) -> list[Any]:
    pending = getattr(session, "pending_action", None) if session is not None else None
    options = []
    if pending is not None:
        # Opciones presentadas viven en suggested_question / missing; usamos portafolio
        # filtrado por intent pendiente cuando es posible.
        intent = str(getattr(pending, "intent_id", "") or "")
        if intent in ("ACCOUNT_BALANCE_READ", "ACCOUNT_MOVEMENTS_READ", "PORTFOLIO_QUERY"):
            options = list(filter_active_by_type(snapshot, _ACCOUNT_TYPES))
        elif intent == "CREDIT_CARD_DETAIL_READ":
            options = list(filter_active_by_type(snapshot, ("CREDIT_CARD",)))
        elif intent == "LOAN_DETAIL_READ":
            options = list(filter_active_by_type(snapshot, ("LOAN",)))
        elif intent == "TERM_DEPOSIT_DETAIL_READ":
            options = list(filter_active_by_type(snapshot, ("TERM_DEPOSIT",)))
    if not options:
        options = list(filter_active_by_type(snapshot, _ACCOUNT_TYPES))
    return options


def _filter_by_currency(pool: list[Any], currency: str | None) -> list[Any]:
    if not currency:
        return pool
    return [p for p in pool if str(getattr(p, "currency", "")).upper() == currency]


def _product_in_portfolio(snapshot: CustomerContextSnapshot, product_id: str) -> Any | None:
    return next(
        (
            p
            for p in snapshot.products
            if p.product_id == product_id and str(p.status).lower() == "active"
        ),
        None,
    )


def resolve_product_reference(
    question: str,
    snapshot: CustomerContextSnapshot,
    session: Any | None = None,
    *,
    pool: list[Any] | None = None,
) -> ContinuityResolution | None:
    """Interpreta moneda, ordinal, deíxis y 'la otra' sobre candidatos reales."""
    text = (question or "").strip()
    if not text:
        return None

    candidates = list(pool) if pool is not None else _candidate_pool(snapshot, session)
    if not candidates:
        return ContinuityResolution(
            product_id="",
            product_kind="account",
            field=_field_from_question(text),
            intent_id="ACCOUNT_BALANCE_READ",
            reason="no_candidates",
            missing=True,
        )

    currency = _currency_from_text(text)
    filtered = _filter_by_currency(candidates, currency)
    pending = getattr(session, "pending_action", None) if session is not None else None
    focus = getattr(session, "product_focus", None) if session is not None else None
    last = getattr(session, "last_resolved", None) if session is not None else None

    # Campo: priorizar query_spec pendiente salvo cambio explícito de campo en la pregunta
    field_default = "balance"
    original_q = text
    if pending is not None:
        field_default = _packet_field_from_spec(
            getattr(pending, "query_spec", None),
            _field_from_question(getattr(pending, "original_question", "") or text),
        )
        original_q = str(getattr(pending, "original_question", "") or text)
        # Si el usuario cambia el campo en el mismo turno ("saldo actual de la de pesos")
        asked = _field_from_question(text, default="")
        if asked and asked != field_default and any(
            s in text.lower()
            for s in ("saldo", "disponible", "movimiento", "balance", "actual")
        ):
            field_default = asked
            original_q = text

    # Moneda no soportada / inexistente en portafolio durante selección pendiente
    if pending is not None and _mentions_unsupported_currency(text):
        return ContinuityResolution(
            product_id="",
            product_kind="account",
            field=field_default,
            intent_id="ACCOUNT_BALANCE_READ",
            reason="currency_missing",
            original_question=original_q,
            missing=True,
        )

    # Moneda: selección pendiente, cambio explícito o referencia corta por divisa
    short_currency_pick = bool(
        currency
        and len(text) < 80
        and (
            pending is not None
            or _is_explicit_switch(text)
            or re.search(r"\b(la|el|cuenta|ahora)\b", text.lower())
        )
    )
    if currency and short_currency_pick:
        field_for_ccy = (
            field_default
            if pending is not None
            else _field_from_question(text, field_default)
        )
        if len(filtered) == 1:
            prod = filtered[0]
            kind = _kind_for_product(prod)
            return ContinuityResolution(
                product_id=prod.product_id,
                product_kind=kind,
                field=field_for_ccy,
                intent_id=_intent_for_kind(kind),
                reason="currency_unique",
                original_question=original_q,
            )
        if len(filtered) == 0:
            return ContinuityResolution(
                product_id="",
                product_kind="account",
                field=field_for_ccy,
                intent_id="ACCOUNT_BALANCE_READ",
                reason="currency_missing",
                original_question=original_q,
                missing=True,
            )
        return ContinuityResolution(
            product_id="",
            product_kind="account",
            field=field_for_ccy,
            intent_id="ACCOUNT_BALANCE_READ",
            reason="currency_ambiguous",
            original_question=original_q,
            ambiguous=True,
            candidates=tuple(p.product_id for p in filtered),
        )

    # Ordinal sobre opciones presentadas
    ord_idx = _ordinal_index(text)
    if ord_idx is not None:
        ordered = filtered if currency else candidates
        if 1 <= ord_idx <= len(ordered):
            prod = ordered[ord_idx - 1]
            kind = _kind_for_product(prod)
            return ContinuityResolution(
                product_id=prod.product_id,
                product_kind=kind,
                field=field_default,
                intent_id=_intent_for_kind(kind),
                reason="ordinal",
                original_question=original_q,
            )
        return ContinuityResolution(
            product_id="",
            product_kind="account",
            field=field_default,
            intent_id="ACCOUNT_BALANCE_READ",
            reason="ordinal_out_of_range",
            original_question=original_q,
            missing=True,
        )

    # "la otra" respecto al foco / last_resolved
    if _is_other_ref(text):
        current_id = None
        if focus is not None and getattr(focus, "product_id", None):
            current_id = str(focus.product_id)
        elif last is not None and getattr(last, "account_ref", None):
            current_id = str(last.account_ref)
        others = [p for p in candidates if p.product_id != current_id]
        if len(others) == 1:
            prod = others[0]
            kind = _kind_for_product(prod)
            return ContinuityResolution(
                product_id=prod.product_id,
                product_kind=kind,
                field=_field_from_question(text, field_default),
                intent_id=_intent_for_kind(kind),
                reason="other_unique",
                original_question=original_q,
            )
        return ContinuityResolution(
            product_id="",
            product_kind="account",
            field=field_default,
            intent_id="ACCOUNT_BALANCE_READ",
            reason="other_ambiguous",
            ambiguous=True,
            candidates=tuple(p.product_id for p in others),
        )

    # "esa cuenta" → foco / last_resolved si pertenece y es elegible
    if _is_deictic_same(text):
        ref = None
        if last is not None and getattr(last, "account_ref", None):
            ref = str(last.account_ref)
        elif focus is not None and getattr(focus, "product_id", None):
            ref = str(focus.product_id)
        if ref:
            prod = _product_in_portfolio(snapshot, ref)
            if prod is None:
                return ContinuityResolution(
                    product_id="",
                    product_kind="account",
                    field=_field_from_question(text, field_default),
                    intent_id="ACCOUNT_BALANCE_READ",
                    reason="deictic_not_owned",
                    missing=True,
                )
            # No reutilizar si la petición pide otra moneda incompatible
            if currency and str(prod.currency).upper() != currency:
                return ContinuityResolution(
                    product_id="",
                    product_kind="account",
                    field=_field_from_question(text, field_default),
                    intent_id="ACCOUNT_BALANCE_READ",
                    reason="deictic_currency_conflict",
                    missing=True,
                )
            kind = _kind_for_product(prod)
            return ContinuityResolution(
                product_id=prod.product_id,
                product_kind=kind,
                field=_field_from_question(text, field_default),
                intent_id=_intent_for_kind(kind),
                reason="deictic_focus",
                original_question=original_q,
            )

    return None


def pending_is_product_selection(session: Any | None) -> bool:
    if session is None:
        return False
    pending = getattr(session, "pending_action", None)
    if pending is None:
        return False
    missing = getattr(pending, "missing_requirements", None) or []
    return "account_ref" in missing


def apply_continuity_to_packet(
    question: str,
    snapshot: CustomerContextSnapshot,
    session: Any | None,
    packet: Any,
) -> Any:
    """Enriquece IntentPacket con hint/campo si la continuidad es inequívoca."""
    if packet is None:
        return packet
    resolution = resolve_product_reference(question, snapshot, session)
    if resolution is None or resolution.ambiguous or resolution.missing or not resolution.product_id:
        return packet

    # No forzar producto previo contra petición explícita incompatible (ya filtrado)
    packet.product = resolution.product_kind
    packet.field = resolution.field
    packet.product_hint_digits = resolution.product_id
    packet.needs_clarification = False
    packet.family = "personal"
    packet.confidence = max(float(getattr(packet, "confidence", 0) or 0), 0.9)
    rationale = getattr(packet, "rationale", None) or getattr(packet, "source", "")
    packet.rationale = f"{rationale}|continuity:{resolution.reason}"
    return packet


def pending_field_question(session: Any | None) -> str:
    if session is None:
        return ""
    pending = getattr(session, "pending_action", None)
    if pending is None:
        return ""
    oq = str(getattr(pending, "original_question", "") or "")
    return query_question(getattr(pending, "query_spec", None), oq) or oq


def try_pending_continuity_fastpath(
    question: str,
    snapshot: CustomerContextSnapshot,
    session: Any | None,
) -> tuple[str, list[dict], str, str, str | None] | None:
    """Resultado compartido para fastpath y brain ante selección pendiente / deíxis.

    Returns:
        (status, actions, text, intent_id, account_ref) o None si no aplica.
    """
    resolved = resolve_product_reference(question, snapshot, session)
    if resolved is None:
        return None

    # Sin pending solo aceptamos deíxis/cambio/ordinal inequívocos
    if not pending_is_product_selection(session):
        if resolved.reason not in (
            "deictic_focus",
            "currency_unique",
            "ordinal",
            "other_unique",
        ):
            return None
        if not resolved.product_id:
            return None
        # Pregunta completa de saldo/disponible con moneda → specific_balance, no continuity
        if resolved.reason == "currency_unique":
            qlow = (question or "").lower()
            full_field_ask = any(
                s in qlow
                for s in (
                    "cual es",
                    "cuál es",
                    "cuanto",
                    "cuánto",
                    "dame el",
                    "dime el",
                    "quiero",
                    "necesito",
                    "consultar",
                )
            ) and any(s in qlow for s in ("balance", "saldo", "disponible", "cuenta"))
            if full_field_ask and len(qlow) > 28:
                return None

    from genesis_cognitive.brain.grounded_executor import execute_grounded
    from genesis_cognitive.brain.intent_types import IntentPacket

    def _balance_action(account_ref: str | None) -> dict:
        return {
            "sequence": 1,
            "intent_id": "ACCOUNT_BALANCE_READ",
            "capability_candidate": "ACCOUNT_BALANCE",
            "selected_route": "PERSONAL_READ",
            "detected_entities": {"account_ref": account_ref},
            "missing_requirements": [] if account_ref else ["account_ref"],
            "depends_on": [],
            "confidence": 1.0,
        }

    if resolved.missing:
        greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
        return (
            "VALID_CONTRACT",
            [_balance_action(None)],
            f"{greeting}no encuentro un producto activo con esa referencia en tu portafolio.",
            "ACCOUNT_BALANCE_READ",
            None,
        )
    if resolved.ambiguous or not resolved.product_id:
        if not pending_is_product_selection(session):
            return None
        return (
            "CLARIFICATION_REQUIRED",
            [_balance_action(None)],
            "¿A cuál producto te refieres?",
            "ACCOUNT_BALANCE_READ",
            None,
        )

    packet = IntentPacket(
        "personal",
        resolved.product_kind,
        resolved.field,
        confidence=0.96,
        product_hint_digits=resolved.product_id,
        source="heuristic",
        rationale=f"continuity:{resolved.reason}",
    )
    gr = execute_grounded(packet, snapshot, question, session=session)
    if not (gr.text or "").strip():
        return None
    if gr.status not in ("VALID_CONTRACT", "CLARIFICATION_REQUIRED"):
        return None
    return (
        gr.status,
        gr.actions or [_balance_action(resolved.product_id)],
        gr.text,
        gr.intent_id,
        gr.account_ref or resolved.product_id,
    )
