"""Resolución contextual de tasa personal (préstamo vs DAP) y preguntas mixtas.

No fija préstamo como interpretación universal: decide por portafolio + foco.
"""

from __future__ import annotations

from typing import Any

from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot
from genesis_cognitive.context.product_display import display_label_in_context, filter_active_by_type
from genesis_cognitive.router.faq_guardrail import (
    _definition_hit_is_relevant,
    _is_explicit_knowledge_definition,
    is_mixed_personal_and_knowledge_question,
    match_faq,
)
from genesis_cognitive.router.final_response_agent import (
    build_deposit_detail_response,
    build_loan_detail_response,
)


def _active_loans(snapshot: CustomerContextSnapshot) -> list:
    return [
        p
        for p in snapshot.products
        if p.product_type == "LOAN" and str(p.status).lower() == "active"
    ]


def _active_daps(snapshot: CustomerContextSnapshot) -> list:
    return filter_active_by_type(snapshot, ("TERM_DEPOSIT",))


def is_personal_rate_question(text: str) -> bool:
    """Pregunta de tasa de producto propio (no glosario)."""
    t = (text or "").lower().strip()
    if not t:
        return False
    if _is_explicit_knowledge_definition(t) and not is_mixed_personal_and_knowledge_question(t):
        return False
    if "tasa" not in t and "interés" not in t and "interes" not in t:
        return False
    # Definición pura ("qué significa tasa") sin posesivo/producto → no personal
    if _is_explicit_knowledge_definition(t) and not any(
        s in t for s in ("mi ", "mis ", "prestamo", "préstamo", "deposito", "depósito", "certificado", "dap")
    ):
        return False
    return True


def _focus_kind(session: Any | None) -> str | None:
    if session is None:
        return None
    focus = getattr(session, "product_focus", None)
    if focus is None:
        return None
    kind = str(getattr(focus, "kind", "") or "").upper()
    if kind in ("LOAN", "TERM_DEPOSIT", "DAP", "ACCOUNT", "CREDIT_CARD"):
        if kind == "DAP":
            return "TERM_DEPOSIT"
        return kind
    # Inferir por intent
    intent = str(getattr(focus, "intent_id", "") or "")
    if "LOAN" in intent:
        return "LOAN"
    if "TERM_DEPOSIT" in intent or "DEPOSIT" in intent:
        return "TERM_DEPOSIT"
    return kind or None


def _focus_product_id(session: Any | None) -> str | None:
    if session is None:
        return None
    focus = getattr(session, "product_focus", None)
    if focus is not None and getattr(focus, "product_id", None):
        return str(focus.product_id)
    last = getattr(session, "last_resolved", None)
    if last is not None and getattr(last, "account_ref", None):
        return str(last.account_ref)
    return None


def _text_names_loan(t: str) -> bool:
    return any(s in t for s in ("prestamo", "préstamo", "credito", "crédito", "hipotec"))


def _text_names_dap(t: str) -> bool:
    return any(
        s in t
        for s in ("deposito", "depósito", "certificado", "dap", "cdt", "plazo")
    )


def _loan_action(ref: str | None) -> dict:
    return {
        "sequence": 1,
        "intent_id": "LOAN_DETAIL_READ",
        "capability_candidate": "LOAN_DETAIL",
        "selected_route": "PERSONAL_READ",
        "detected_entities": {"account_ref": ref, "knowledge_topic": None},
        "missing_requirements": [] if ref else ["account_ref"],
        "depends_on": [],
        "confidence": 1.0,
    }


def _dap_action(ref: str | None) -> dict:
    return {
        "sequence": 1,
        "intent_id": "TERM_DEPOSIT_DETAIL_READ",
        "capability_candidate": "TERM_DEPOSIT_DETAIL",
        "selected_route": "PERSONAL_READ",
        "detected_entities": {"account_ref": ref, "knowledge_topic": None},
        "missing_requirements": [] if ref else ["account_ref"],
        "depends_on": [],
        "confidence": 1.0,
    }


def _loan_rate_text(snapshot: CustomerContextSnapshot, loan_prod, question: str) -> str:
    loan = next((ln for ln in snapshot.loans if ln.product_id == loan_prod.product_id), None)
    if loan is not None:
        return build_loan_detail_response(
            question, loan.to_detail_dict(), snapshot.display_name,
        )
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
    rate = getattr(loan_prod, "interest_rate", None)
    label = display_label_in_context(loan_prod, _active_loans(snapshot))
    if rate is not None:
        return f"{greeting}la tasa de tu {label} es {rate}% anual."
    return f"{greeting}la tasa de tu {label} no está disponible en este momento."


def _dap_rate_text(snapshot: CustomerContextSnapshot, dap, question: str) -> str:
    label = display_label_in_context(dap, _active_daps(snapshot))
    return build_deposit_detail_response(question, dap, snapshot.display_name, label)


def apply_personal_rate_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Resuelve tasa personal según productos elegibles y foco (sin overfit a préstamo)."""
    if snapshot is None or not is_personal_rate_question(raw_text):
        return None
    # Mixtas: las maneja apply_mixed_personal_knowledge_guardrail
    if is_mixed_personal_and_knowledge_question(raw_text):
        return None

    t = (raw_text or "").lower()
    loans = _active_loans(snapshot)
    daps = _active_daps(snapshot)
    focus_kind = _focus_kind(session)
    focus_id = _focus_product_id(session)

    # Ancla explícita en el texto
    if _text_names_loan(t) and not _text_names_dap(t):
        if not loans:
            name = snapshot.display_name or ""
            g = f"{name}, " if name else ""
            return (
                "VALID_CONTRACT",
                [_loan_action(None)],
                f"{g}no tienes préstamos activos para consultar la tasa.",
                None,
            )
        if len(loans) == 1:
            p = loans[0]
            return (
                "VALID_CONTRACT",
                [_loan_action(p.product_id)],
                _loan_rate_text(snapshot, p, raw_text),
                None,
            )
        from genesis_cognitive.context.app_channel import build_loan_disambiguation_question
        q = build_loan_disambiguation_question(loans)
        return "CLARIFICATION_REQUIRED", [_loan_action(None)], q, None

    if _text_names_dap(t) and not _text_names_loan(t):
        if not daps:
            name = snapshot.display_name or ""
            g = f"{name}, " if name else ""
            return (
                "VALID_CONTRACT",
                [_dap_action(None)],
                f"{g}no tienes depósitos a plazo activos para consultar la tasa.",
                None,
            )
        if len(daps) == 1:
            p = daps[0]
            return (
                "VALID_CONTRACT",
                [_dap_action(p.product_id)],
                _dap_rate_text(snapshot, p, raw_text),
                None,
            )
        q = "¿De cuál certificado o depósito a plazo quieres la tasa?"
        return "CLARIFICATION_REQUIRED", [_dap_action(None)], q, None

    # Foco inequívoco
    if focus_id and focus_kind == "LOAN":
        p = next((x for x in loans if x.product_id == focus_id), None)
        if p is not None:
            return (
                "VALID_CONTRACT",
                [_loan_action(p.product_id)],
                _loan_rate_text(snapshot, p, raw_text),
                None,
            )
    if focus_id and focus_kind == "TERM_DEPOSIT":
        p = next((x for x in daps if x.product_id == focus_id), None)
        if p is not None:
            return (
                "VALID_CONTRACT",
                [_dap_action(p.product_id)],
                _dap_rate_text(snapshot, p, raw_text),
                None,
            )

    # Una sola familia elegible
    if loans and not daps:
        if len(loans) == 1:
            p = loans[0]
            return (
                "VALID_CONTRACT",
                [_loan_action(p.product_id)],
                _loan_rate_text(snapshot, p, raw_text),
                None,
            )
        from genesis_cognitive.context.app_channel import build_loan_disambiguation_question
        return (
            "CLARIFICATION_REQUIRED",
            [_loan_action(None)],
            build_loan_disambiguation_question(loans),
            None,
        )
    if daps and not loans:
        if len(daps) == 1:
            p = daps[0]
            return (
                "VALID_CONTRACT",
                [_dap_action(p.product_id)],
                _dap_rate_text(snapshot, p, raw_text),
                None,
            )
        return (
            "CLARIFICATION_REQUIRED",
            [_dap_action(None)],
            "¿De cuál certificado o depósito a plazo quieres la tasa?",
            None,
        )

    # Ambas familias sin foco → aclarar (no asumir préstamo)
    if loans and daps:
        name = snapshot.display_name or ""
        g = f"{name}, " if name else ""
        return (
            "CLARIFICATION_REQUIRED",
            [_loan_action(None)],
            (
                f"{g}puedo consultarte la tasa de tu préstamo o de tu depósito a plazo. "
                "¿Cuál de los dos te interesa?"
            ),
            None,
        )

    name = snapshot.display_name or ""
    g = f"{name}, " if name else ""
    return (
        "VALID_CONTRACT",
        [],
        f"{g}no tengo un producto con tasa consultable en tu portafolio activo.",
        None,
    )


# Evidencia sintética: solo vía inyección de pruebas (no env en despliegue)
_SYNTHETIC_RATE_DEFINITION = (
    "[evidencia-sintetica-test] La tasa de interés es el porcentaje que el banco "
    "aplica sobre el capital de un préstamo o depósito en un periodo determinado."
)

# Callable opcional inyectado por tests: () -> str | None
_definition_evidence_override: Any | None = None


def set_definition_evidence_override(fn: Any | None) -> None:
    """Hook de prueba: inyecta evidencia sintética sin variables de entorno."""
    global _definition_evidence_override
    _definition_evidence_override = fn


def _definition_for_mixed(question: str) -> tuple[str | None, str]:
    """(texto definición, fuente). Fuente: faq | synthetic_test | missing."""
    hit = match_faq("¿Qué significa tasa de interés?")
    if hit and hit.get("answer") and _definition_hit_is_relevant(
        "¿Qué significa tasa de interés?", hit,
    ):
        return str(hit["answer"]).strip(), "faq"
    if callable(_definition_evidence_override):
        synthetic = _definition_evidence_override()
        if synthetic:
            return str(synthetic), "synthetic_test"
    return None, "missing"


def apply_mixed_personal_knowledge_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Conserva objetivo personal + definición; no descarta silenciosamente."""
    if snapshot is None or not is_mixed_personal_and_knowledge_question(raw_text):
        return None

    t = (raw_text or "").lower()
    # Parte personal: tasa de préstamo (u otro producto nombrado)
    personal_q = raw_text
    if "tasa" in t:
        # Extraer lado personal aproximado
        for sep in (" y qué significa", " y que significa", " y qué es", " y que es"):
            if sep in t:
                idx = t.index(sep)
                personal_q = raw_text[:idx].strip(" ¿?") or "cuál es mi tasa"
                break

    # Forzar ancla préstamo si el texto lo nombra
    rate_out = None
    if _text_names_loan(t):
        # Resolver solo préstamos
        loans = _active_loans(snapshot)
        if not loans:
            personal_status = "VALID_CONTRACT"
            personal_text = (
                f"{snapshot.display_name}, no tienes préstamos activos para consultar la tasa."
                if snapshot.display_name
                else "No tienes préstamos activos para consultar la tasa."
            )
            personal_actions: list[dict] = [_loan_action(None)]
            personal_ref = None
            needs_clarif = False
        elif len(loans) == 1:
            p = loans[0]
            personal_status = "VALID_CONTRACT"
            personal_text = _loan_rate_text(snapshot, p, personal_q)
            personal_actions = [_loan_action(p.product_id)]
            personal_ref = p.product_id
            needs_clarif = False
        else:
            from genesis_cognitive.context.app_channel import (
                build_loan_disambiguation_question,
            )
            personal_status = "CLARIFICATION_REQUIRED"
            personal_text = build_loan_disambiguation_question(loans)
            personal_actions = [_loan_action(None)]
            personal_ref = None
            needs_clarif = True
    else:
        rate_out = apply_personal_rate_guardrail(snapshot, personal_q, session)
        if rate_out is None:
            return None
        personal_status, personal_actions, personal_text, _ = rate_out
        personal_ref = (personal_actions[0].get("detected_entities") or {}).get("account_ref") if personal_actions else None
        needs_clarif = personal_status == "CLARIFICATION_REQUIRED"

    def_text, def_source = _definition_for_mixed(raw_text)
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""

    if needs_clarif:
        # Aclarar producto SIN perder la explicación pendiente
        pending_note = (
            "Cuando me indiques el producto, también te explicaré qué significa la tasa."
            if def_text
            else (
                "Cuando me indiques el producto te doy la tasa; "
                "aún no tengo evidencia local suficiente para la definición."
            )
        )
        # Sembrar pending en session si existe
        if session is not None:
            from genesis_cognitive.context.reactive_store import PendingAction
            from genesis_cognitive.context.query_spec import build_query_spec

            session.pending_action = PendingAction(
                intent_id="LOAN_DETAIL_READ",
                capability_candidate="LOAN_DETAIL",
                selected_route="PERSONAL_READ",
                detected_entities={
                    "account_ref": None,
                    "knowledge_topic": "tasa_interes_definicion",
                    "mixed_pending_definition": "1",
                },
                missing_requirements=["account_ref"],
                suggested_question=personal_text or "",
                original_question=raw_text,
                query_spec=build_query_spec(raw_text, "LOAN_DETAIL_READ"),
            )
        combined = f"{personal_text}\n\n{pending_note}".strip()
        return "CLARIFICATION_REQUIRED", personal_actions, combined, None

    parts: list[str] = []
    if personal_text:
        parts.append(personal_text.strip())
    if def_text:
        # Evitar duplicar saludo
        body = def_text
        if greeting and body.lower().startswith((snapshot.display_name or "").lower()):
            pass
        parts.append(f"Sobre qué significa: {body}")
    else:
        parts.append(
            "Sobre la definición: no pude resolverla con evidencia disponible en esta fuente "
            f"(origen={def_source}); la parte de tu tasa personal sí quedó cubierta arriba."
        )

    text = "\n\n".join(parts)
    actions = list(personal_actions or [])
    if actions:
        ents = dict(actions[0].get("detected_entities") or {})
        ents["knowledge_topic"] = "tasa_interes_definicion"
        ents["mixed_definition_source"] = def_source
        if personal_ref:
            ents["account_ref"] = personal_ref
        actions[0] = {**actions[0], "detected_entities": ents}
    return personal_status, actions, text, None
