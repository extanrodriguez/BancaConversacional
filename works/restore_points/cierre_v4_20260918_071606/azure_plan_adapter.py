"""Adaptador: TurnInterpretation / acciones Azure → TurnPlan ejecutable.

El modelo propone significado; el servidor deriva dominio/campos/autorización.
No inventa montos. No concede permisos.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from genesis_cognitive.brain.turn_plan import (
    InvalidTurnPlanError,
    PlanTask,
    TurnPlan,
    validate_turn_plan,
)
from genesis_cognitive.decision.types import SemanticAction, TurnInterpretation


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = "".join(
        c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", t).strip()


def _field_from_question(q: str, intent_id: str) -> list[str]:
    n = _norm(q)
    intent = (intent_id or "").upper()

    # Institucional / glosario: solo campos de conocimiento
    if intent in ("BUSINESS_KNOWLEDGE_QUERY", "KNOWLEDGE_QUERY"):
        fields: list[str] = []
        if "significa" in n or "que es" in n or "qué es" in n:
            if "tasa" in n:
                return ["interest_rate"]
            if "disponible" in n:
                return ["available_balance"]
        if any(s in n for s in ("mision", "misión")):
            fields.append("mision")
        if any(s in n for s in ("vision", "visión")):
            fields.append("vision")
        return fields or ["info"]

    fields = []
    if intent == "ACCOUNT_BALANCE_READ":
        if any(s in n for s in ("disponible", "puedo contar", "con cuanto", "liquidez")):
            fields.append("available")
        if any(s in n for s in ("saldo contable", "saldo actual", "ledger", "balance actual")):
            fields.append("balance")
        if not fields:
            fields = ["available"] if any(
                s in n for s in ("disponible", "contar")
            ) else ["balance"]
        return fields

    if intent == "LOAN_DETAIL_READ":
        if "tasa" in n:
            fields.append("rate")
        if any(s in n for s in ("fecha de pago", "cuando pago", "cuota")):
            fields.append("due_date")
        if any(s in n for s in ("capital", "deuda", "debo", "saldo")):
            fields.append("principal")
        return fields or (["rate"] if "tasa" in n else ["principal"])

    if intent == "CREDIT_CARD_DETAIL_READ":
        if any(s in n for s in ("disponible",)):
            fields.append("available")
        if any(s in n for s in ("debo", "deuda", "adeudado")):
            fields.append("balance")
        if any(s in n for s in ("fecha de pago", "cuando pago")):
            fields.append("due_date")
        return fields or ["available"]

    if intent == "TERM_DEPOSIT_DETAIL_READ":
        if "tasa" in n:
            fields.append("rate")
        if any(s in n for s in ("vence", "vencimiento")):
            fields.append("maturity")
        return fields or ["rate"]

    if intent == "ACCOUNT_MOVEMENTS_READ":
        return ["movements"]

    return ["info"]


def _map_action(
    action: SemanticAction,
    question: str,
    *,
    seq_to_id: dict[int, str],
) -> PlanTask:
    intent = (action.intent_id or "").upper()
    ent = action.detected_entities
    account_ref = getattr(ent, "account_ref", None) if ent else None
    currency = getattr(ent, "currency", None) if ent else None
    topic = getattr(ent, "knowledge_topic", None) if ent else None
    missing = list(action.missing_requirements or [])
    deps = [seq_to_id[d] for d in (action.depends_on or []) if d in seq_to_id]
    tid = seq_to_id[action.sequence]
    filters: dict[str, Any] = {}
    if currency:
        filters["currency"] = str(currency).upper()
    if topic:
        filters["knowledge_topic"] = str(topic)

    status = "ready"
    unresolved: list[str] = []
    if missing or (intent.endswith("_READ") and not account_ref and intent not in (
        "BUSINESS_KNOWLEDGE_QUERY", "PORTFOLIO_LIST_READ", "PORTFOLIO_LIST",
    )):
        # Clarificación solo si el intent personal carece de entidad y hay ambigüedad
        if intent in (
            "ACCOUNT_BALANCE_READ", "LOAN_DETAIL_READ", "CREDIT_CARD_DETAIL_READ",
            "TERM_DEPOSIT_DETAIL_READ", "ACCOUNT_MOVEMENTS_READ",
        ) and not account_ref:
            status = "needs_clarification"
            unresolved = ["entity_ref"]

    if intent == "ACCOUNT_BALANCE_READ":
        return PlanTask(
            id=tid, domain="personal", action="read_field", object="account",
            fields=_field_from_question(question, intent),
            entity_ref=account_ref, filters=filters, depends_on=deps,
            unresolved_slots=unresolved, status=status,
        )
    if intent == "ACCOUNT_MOVEMENTS_READ":
        return PlanTask(
            id=tid, domain="personal", action="read_field", object="account",
            fields=["movements"], entity_ref=account_ref, filters=filters,
            depends_on=deps, status="unsupported",
        )
    if intent == "LOAN_DETAIL_READ":
        return PlanTask(
            id=tid, domain="personal", action="read_field", object="loan",
            fields=_field_from_question(question, intent),
            entity_ref=account_ref, filters=filters, depends_on=deps,
            unresolved_slots=unresolved, status=status,
        )
    if intent == "CREDIT_CARD_DETAIL_READ":
        return PlanTask(
            id=tid, domain="personal", action="read_field", object="credit_card",
            fields=_field_from_question(question, intent),
            entity_ref=account_ref, filters=filters, depends_on=deps,
            unresolved_slots=unresolved, status=status,
        )
    if intent == "TERM_DEPOSIT_DETAIL_READ":
        return PlanTask(
            id=tid, domain="personal", action="read_field", object="term_deposit",
            fields=_field_from_question(question, intent),
            entity_ref=account_ref, filters=filters, depends_on=deps,
            unresolved_slots=unresolved, status=status,
        )
    if intent in ("PORTFOLIO_LIST", "PORTFOLIO_LIST_READ", "PRODUCT_LIST_READ"):
        return PlanTask(
            id=tid, domain="personal", action="list", object="portfolio",
            fields=["list"], depends_on=deps, status="ready",
        )
    if intent in ("BUSINESS_KNOWLEDGE_QUERY", "KNOWLEDGE_QUERY"):
        fields = _field_from_question(question, intent)
        obj = "glossary" if fields and fields[0] in ("interest_rate", "available_balance") else "bank"
        return PlanTask(
            id=tid, domain="institutional", action="define", object=obj,
            fields=fields or ["info"], filters=filters, depends_on=deps, status="ready",
        )
    if intent in ("CLARIFICATION", "CLARIFY"):
        return PlanTask(
            id=tid, domain="none", action="clarify", object="none",
            fields=["other"], unresolved_slots=missing or ["entity_ref"],
            depends_on=deps, status="needs_clarification",
        )
    if intent in ("SECURITY_GUARDRAIL", "REFUSE"):
        return PlanTask(
            id=tid, domain="none", action="refuse", object="secret",
            fields=["auth_secret"], status="ready",
        )
    # Fallback: unsupported segment
    return PlanTask(
        id=tid, domain="none", action="clarify", object="none",
        fields=["other"], status="needs_clarification",
        unresolved_slots=["intent"],
        filters={"unmapped_intent": intent},
    )


def _infer_transition(question: str, session: Any | None) -> str:
    n = _norm(question)
    if any(s in n for s in ("no, la", "no la", "me referia", "me refería", "la corriente", "la de ahorros")):
        return "correction"
    if any(s in n for s in ("volviendo", "retomando", "volvamos", "esa cuenta", "ese prestamo")):
        return "continue"
    if any(s in n for s in ("el segundo", "la segunda", "el primero", "la primera")):
        return "selection"
    if session is not None and getattr(session, "pending_tasks", None):
        if any(s in n for s in ("la de", "dolares", "dólares", "usd", "dop", "esa", "ese")):
            return "selection"
    return "none"


def interpretation_to_turn_plan(
    interpretation: TurnInterpretation,
    question: str,
    *,
    session: Any | None = None,
    source: str = "azure_plan",
) -> TurnPlan:
    """Convierte acciones canónicas en TurnPlan validado."""
    actions = list(interpretation.actions or [])
    seq_to_id = {a.sequence: f"t{a.sequence}" for a in actions}
    tasks = [_map_action(a, question, seq_to_id=seq_to_id) for a in actions]
    # Si el modo es CLARIFICATION sin acciones útiles
    if not tasks and str(getattr(interpretation.mode, "value", interpretation.mode)) == "CLARIFICATION":
        tasks = [PlanTask(
            id="t1", domain="none", action="clarify", object="none",
            fields=["other"], status="needs_clarification",
            unresolved_slots=["entity_ref"],
        )]
    transition = _infer_transition(question, session)
    plan = TurnPlan(tasks=tasks, transition=transition, source=source)
    errors = validate_turn_plan(plan)
    if errors:
        raise InvalidTurnPlanError(errors)
    return plan


def is_unequivocal_structured_shortcut(
    question: str,
    session: Any | None,
) -> tuple[bool, str]:
    """Atajos solo si cubren TODA la solicitud (UI / selección estructurada).

    No habilitar por encontrar «misión», «disponible» o «segunda» en una
    pregunta compuesta.
    """
    q = (question or "").strip()
    n = _norm(q)
    if not n:
        return False, "empty"
    # Selección APK/opción estructurada: solo dígitos o "opcion N"
    if re.fullmatch(r"\d{1,2}", n) or re.fullmatch(r"opcion\s+\d{1,2}", n):
        if session is not None and (
            getattr(session, "pending_action", None) or getattr(session, "pending_tasks", None)
        ):
            return True, "structured_option_index"
    # Secretos: siempre atajo refuse local
    from genesis_cognitive.brain.security_secrets import is_auth_secret_message
    if is_auth_secret_message(q):
        return True, "auth_secret_refuse"
    # Titularidad de terceros inequívoca
    if any(s in n for s in ("de mi esposa", "de mi esposo", "de mi hijo", "de otra persona")) and (
        "saldo" in n or "cuenta" in n or "disponible" in n
    ):
        return True, "third_party_refuse"
    return False, "open_language"
