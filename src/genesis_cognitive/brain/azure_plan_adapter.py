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


def _has_token(text: str, token: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9áéíóúñ]){re.escape(token)}(?![a-z0-9áéíóúñ])", text or ""))


def _wants_rate_definition(q: str) -> bool:
    n = _norm(q)
    # «cuál es mi tasa» es personal, no glosario
    if re.search(r"\bmi\s+tasa\b", n) and "significa" not in n:
        return False
    return "tasa" in n and any(
        s in n
        for s in (
            "significa",
            "que significa",
            "que es la tasa",
            "que es tasa",
            "definicion",
            "definicion de la tasa",
            "quiere decir",
        )
    )


def _institutional_fields_from_question(q: str) -> list[str]:
    n = _norm(q)
    fields: list[str] = []
    if any(s in n for s in ("mision", "misión")):
        fields.append("mision")
    if any(s in n for s in ("vision", "visión")):
        fields.append("vision")
    if _wants_rate_definition(n):
        fields.append("interest_rate")
    if re.search(
        r"(que|qué)\s+(significa|es)\s+(el\s+)?saldo\s+disponible",
        n,
    ) or re.search(r"definici[oó]n\s+(del?\s+)?saldo\s+disponible", n):
        fields.append("available_balance")
    return fields


def _account_subtype_from_question(q: str) -> str | None:
    n = _norm(q)
    if "corriente" in n:
        return "CHECKING"
    if "ahorros" in n or "ahorro" in n:
        return "SAVINGS"
    if "nomina" in n or "nómina" in n:
        return "PAYROLL"
    return None


def _field_from_question(q: str, intent_id: str, *, action_topic: str | None = None) -> list[str]:
    n = _norm(q)
    intent = (intent_id or "").upper()
    topic = _norm(action_topic or "")

    # Institucional / glosario: solo campos de conocimiento (por acción, no por frase completa)
    if intent in ("BUSINESS_KNOWLEDGE_QUERY", "KNOWLEDGE_QUERY"):
        if topic in ("mision", "misión", "mission"):
            return ["mision"]
        if topic in ("vision", "visión"):
            return ["vision"]
        if "tasa" in topic or topic in ("interest_rate", "rate", "interes", "interés"):
            return ["interest_rate"]
        if "disponible" in topic:
            return ["available_balance"]
        fields = _institutional_fields_from_question(n)
        if fields:
            # Si la acción es conocimiento y la frase mezcla tasa+definición, preferir glosario
            if "interest_rate" in fields and intent.startswith("BUSINESS"):
                return ["interest_rate"]
            return fields[:1]
        return ["info"]

    fields: list[str] = []
    if intent == "ACCOUNT_BALANCE_READ":
        if any(s in n for s in ("disponible", "puedo contar", "con cuanto", "liquidez")):
            fields.append("available")
        if any(s in n for s in ("saldo contable", "ledger", "balance contable")):
            fields.append("balance")
            return fields
        if any(s in n for s in ("saldo actual", "balance actual")):
            fields.append("balance")
        if not fields:
            # Regla documentada: «saldo» sin calificativo → ledger/saldo actual (contrato bancario)
            fields = ["available"] if any(s in n for s in ("disponible", "contar")) else ["balance"]
        return fields

    if intent == "LOAN_DETAIL_READ":
        if "tasa" in n:
            fields.append("rate")
        if any(s in n for s in ("fecha de pago", "cuando pago", "cuota")):
            fields.append("due_date")
        if any(s in n for s in ("capital", "deuda", "debo")) and "tasa" not in n:
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


def _resolve_account_ref(
    *,
    account_ref: str | None,
    filters: dict[str, Any],
    session: Any | None,
    snapshot: Any | None,
) -> tuple[str | None, str, list[str]]:
    """Devuelve (entity_ref, status, unresolved). Ausencia de tipo = negocio, no error de parseo."""
    if account_ref:
        return account_ref, "ready", []
    subtype = filters.get("account_subtype")
    if snapshot is not None and subtype:
        matches = [
            p for p in snapshot.products
            if p.product_type == subtype and str(p.status).lower() == "active"
        ]
        if len(matches) == 1:
            return matches[0].product_id, "ready", []
        if len(matches) == 0:
            return None, "ready", []  # ejecutor reportará absent
        return None, "needs_clarification", ["entity_ref"]
    # Foco previo si no hay corrección de subtipo
    if session is not None and not subtype:
        pf = getattr(session, "product_focus", None)
        if pf is not None and getattr(pf, "kind", None) == "ACCOUNT" and getattr(pf, "product_id", None):
            return str(pf.product_id), "ready", []
    return None, "needs_clarification", ["entity_ref"]


def _map_action(
    action: SemanticAction,
    question: str,
    *,
    seq_to_id: dict[int, str],
    session: Any | None = None,
    snapshot: Any | None = None,
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

    subtype = _account_subtype_from_question(question)
    if subtype and intent == "ACCOUNT_BALANCE_READ":
        filters["account_subtype"] = subtype

    status = "ready"
    unresolved: list[str] = []
    if intent in (
        "ACCOUNT_BALANCE_READ", "LOAN_DETAIL_READ", "CREDIT_CARD_DETAIL_READ",
        "TERM_DEPOSIT_DETAIL_READ", "ACCOUNT_MOVEMENTS_READ",
    ):
        account_ref, status, unresolved = _resolve_account_ref(
            account_ref=account_ref, filters=filters, session=session, snapshot=snapshot,
        )
        if intent == "LOAN_DETAIL_READ" and not account_ref and snapshot is not None:
            loans = [
                p for p in snapshot.products
                if p.product_type == "LOAN" and str(p.status).lower() == "active"
            ]
            if len(loans) == 1:
                account_ref, status, unresolved = loans[0].product_id, "ready", []
            elif len(loans) > 1:
                status, unresolved = "needs_clarification", ["entity_ref"]
        if missing and status == "ready" and not account_ref:
            status = "needs_clarification"
            unresolved = missing or ["entity_ref"]

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
        fields = _field_from_question(question, intent, action_topic=str(topic or ""))
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
    return PlanTask(
        id=tid, domain="none", action="clarify", object="none",
        fields=["other"], status="needs_clarification",
        unresolved_slots=["intent"],
        filters={"unmapped_intent": intent},
    )


def _infer_transition(question: str, session: Any | None) -> str:
    n = _norm(question)
    # Corrección de foco personal (puede coexistir con solicitud institucional)
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


def _wants_unqualified_personal_rate(n: str) -> bool:
    """«mi tasa» / «tasa de interés» sin acotar a un tipo ni pedir definición."""
    if "tasa" not in n or "significa" in n or _wants_rate_definition(n):
        return False
    if any(
        s in n
        for s in (
            "prestamo", "préstamo", "certificado", "dap", "cdt",
            "tarjeta", "visa", "mastercard", "deposito a plazo", "depósito a plazo",
        )
    ):
        return False
    return bool(
        re.search(r"\bmi\s+tasa\b", n)
        or "tasa de interes" in n
        or "tasa anual" in n
    )


def _portfolio_rate_task(question: str, snapshot: Any | None) -> PlanTask | None:
    """Tasa personal según productos del snapshot (préstamo/DAP/tarjeta con tasa)."""
    if snapshot is None:
        return None
    from genesis_cognitive.brain.plan_interpreter import (
        _active_products,
        _match_portfolio_by_text,
        _plan_field_for_product,
        _product_bears_rate,
    )

    n = _norm(question)
    mentioned = _match_portfolio_by_text(question, snapshot)
    if mentioned:
        rate_pool = [p for p in mentioned if _product_bears_rate(p)]
    else:
        active = _active_products(snapshot)
        if any(s in n for s in ("prestamo", "préstamo")):
            rate_pool = [p for p in active if p.product_type == "LOAN"]
        elif any(s in n for s in ("certificado", "dap", "deposito a plazo", "depósito a plazo", "cdt")):
            rate_pool = [p for p in active if p.product_type == "TERM_DEPOSIT"]
        elif any(s in n for s in ("tarjeta", "visa", "mastercard")):
            rate_pool = [
                p for p in active
                if p.product_type == "CREDIT_CARD" and _product_bears_rate(p)
            ]
        else:
            rate_pool = [p for p in active if _product_bears_rate(p)]
    task, _ = _plan_field_for_product(products=rate_pool, field="rate", n=1)
    return task


def _apply_portfolio_alias_fields(
    tasks: list[PlanTask],
    question: str,
    *,
    snapshot: Any | None,
) -> list[PlanTask]:
    """Si el texto nombra un producto del portafolio, fija entity_ref / campo pedido."""
    if snapshot is None:
        return tasks
    from genesis_cognitive.brain.plan_interpreter import (
        _match_portfolio_by_text,
        _plan_field_for_product,
        _product_bears_maturity,
        _product_bears_rate,
    )

    n = _norm(question)
    matched = _match_portfolio_by_text(question, snapshot)
    if not matched:
        return tasks

    fields: list[str] = []
    if "tasa" in n or "interes" in n:
        fields.append("rate")
    if "disponible" in n:
        fields.append("available")
    elif "saldo" in n or "debo" in n or "adeud" in n:
        fields.append("balance")
    if any(s in n for s in ("vence", "vencimiento", "madurez")):
        fields.append("maturity")
    if any(s in n for s in ("pago minimo", "mínimo", "minimo")):
        fields.append("min_payment")
    if not fields:
        return tasks

    # Sustituye tareas personales vagas del mismo campo por la resolución del alias
    drop_fields = set(fields)
    kept = [
        t for t in tasks
        if not (
            t.domain == "personal"
            and t.action == "read_field"
            and drop_fields.intersection(t.fields or [])
            and not t.entity_ref
        )
    ]
    next_id = len(kept) + 1
    for fld in fields:
        pool = matched
        if fld == "rate":
            pool = [p for p in matched if _product_bears_rate(p)]
        elif fld == "maturity":
            pool = [p for p in matched if _product_bears_maturity(p)]
        task, next_id = _plan_field_for_product(products=pool, field=fld, n=next_id)
        kept.append(task)
    return kept


def _supplement_tasks_from_question(
    tasks: list[PlanTask],
    question: str,
    *,
    snapshot: Any | None,
) -> list[PlanTask]:
    """Completa tareas omitidas por el modelo cuando la frase las exige de forma explícita.

    No inventa montos ni glosarios: solo estructura de plan (definición/misión/visión/cuenta).
    """
    n = _norm(question)
    existing_domains = {(t.domain, (t.fields or [None])[0]) for t in tasks}
    existing_objects = {t.object for t in tasks}
    out = list(tasks)
    next_id = len(out) + 1

    def _add(task: PlanTask) -> None:
        nonlocal next_id
        task.id = f"t{next_id}"
        next_id += 1
        out.append(task)

    # tasa + qué significa → glosario independiente si falta
    if _wants_rate_definition(n):
        has_glossary = any(
            t.domain == "institutional" and t.object == "glossary"
            and "interest_rate" in (t.fields or [])
            for t in out
        )
        has_personal_rate = any(
            t.domain == "personal" and "rate" in (t.fields or [])
            for t in out
        )
        if not has_glossary:
            _add(PlanTask(
                id="tmp", domain="institutional", action="define", object="glossary",
                fields=["interest_rate"], status="ready",
            ))
        if not has_personal_rate and any(s in n for s in (
            "prestamo", "préstamo", "mi tasa", "tasa de mi", "tasa de interes",
            "tasa anual",
        )):
            rate_task = _portfolio_rate_task(question, snapshot)
            if rate_task is not None:
                _add(rate_task)

    # «cuál es mi tasa» / «tasa de interés»: pool real del portafolio (no solo préstamos)
    if _wants_unqualified_personal_rate(n):
        rate_task = _portfolio_rate_task(question, snapshot)
        if rate_task is not None:
            out = [
                t for t in out
                if not (
                    t.domain == "personal"
                    and "rate" in (t.fields or [])
                    and t.action == "read_field"
                )
            ]
            next_id = len(out) + 1
            _add(rate_task)

    # Alias del portafolio (p. ej. «saldo/tasa de mi tarjeta joven»)
    if not _wants_unqualified_personal_rate(n):
        out = _apply_portfolio_alias_fields(out, question, snapshot=snapshot)
        next_id = len(out) + 1

    # cuenta + préstamo en la misma frase
    wants_account = any(s in n for s in ("cuenta", "disponible", "saldo")) and not _wants_rate_definition(n)
    wants_loan_rate = "tasa" in n and any(s in n for s in ("prestamo", "préstamo"))
    if wants_account and wants_loan_rate:
        if "account" not in existing_objects:
            field = "available" if "disponible" in n else "balance"
            accts = []
            if snapshot is not None:
                accts = [
                    p for p in snapshot.products
                    if p.product_type in ("SAVINGS", "CHECKING", "PAYROLL")
                    and str(p.status).lower() == "active"
                ]
            _add(PlanTask(
                id="tmp", domain="personal", action="read_field", object="account",
                fields=[field],
                status="ready" if len(accts) == 1 else ("needs_clarification" if len(accts) > 1 else "ready"),
                entity_ref=accts[0].product_id if len(accts) == 1 else None,
                unresolved_slots=["entity_ref"] if len(accts) > 1 else [],
            ))
        if not any(t.object == "loan" and "rate" in (t.fields or []) for t in out):
            rate_task = _portfolio_rate_task(question, snapshot)
            if rate_task is not None:
                _add(rate_task)

    # corrección + misión/visión
    for fld in _institutional_fields_from_question(n):
        if fld == "interest_rate":
            continue
        key = ("institutional", fld)
        if key in existing_domains:
            continue
        if any(t.domain == "institutional" and fld in (t.fields or []) for t in out):
            continue
        _add(PlanTask(
            id="tmp", domain="institutional", action="define", object="bank",
            fields=[fld], status="ready",
        ))

    # Corrección de subtipo de cuenta: no conservar entity_ref del foco previo
    if any(s in n for s in ("no, la", "no la", "me referia", "me refería", "la corriente", "la de ahorros", "la de nomina", "la de nómina")):
        subtype = None
        if "corriente" in n:
            subtype = "CHECKING"
        elif "ahorros" in n:
            subtype = "SAVINGS"
        elif "nomina" in n or "nómina" in n:
            subtype = "PAYROLL"
        if subtype:
            rewritten: list[PlanTask] = []
            for t in out:
                if t.domain == "personal" and t.object == "account":
                    matches = []
                    if snapshot is not None:
                        matches = [
                            p for p in snapshot.products
                            if p.product_type == subtype and str(p.status).lower() == "active"
                        ]
                    filters = dict(t.filters or {})
                    filters["account_subtype"] = subtype
                    filters["invalidate_prior_focus"] = True
                    if len(matches) == 1:
                        rewritten.append(PlanTask(
                            id=t.id, domain=t.domain, action=t.action, object=t.object,
                            fields=list(t.fields or ["balance"]),
                            filters=filters, entity_ref=matches[0].product_id,
                            status="ready", unresolved_slots=[],
                        ))
                    elif len(matches) > 1:
                        rewritten.append(PlanTask(
                            id=t.id, domain=t.domain, action=t.action, object=t.object,
                            fields=list(t.fields or ["balance"]),
                            filters=filters, entity_ref=None,
                            status="needs_clarification", unresolved_slots=["entity_ref"],
                        ))
                    else:
                        # Ausencia de producto: mantener tarea sin entity para que el
                        # ejecutor declare absent (no sustituir por otro subtipo).
                        rewritten.append(PlanTask(
                            id=t.id, domain=t.domain, action=t.action, object=t.object,
                            fields=list(t.fields or ["balance"]),
                            filters=filters, entity_ref=None,
                            status="ready", unresolved_slots=[],
                        ))
                else:
                    rewritten.append(t)
            out = rewritten

    return out


def interpretation_to_turn_plan(
    interpretation: TurnInterpretation | None,
    question: str,
    *,
    session: Any | None = None,
    snapshot: Any | None = None,
    source: str = "azure_plan",
) -> TurnPlan:
    """Convierte acciones canónicas en TurnPlan validado."""
    if interpretation is None:
        raise InvalidTurnPlanError(["interpretation_missing"])
    actions = list(interpretation.actions or [])
    seq_to_id = {a.sequence: f"t{a.sequence}" for a in actions}
    tasks = [
        _map_action(a, question, seq_to_id=seq_to_id, session=session, snapshot=snapshot)
        for a in actions
    ]
    if not tasks and str(getattr(interpretation.mode, "value", interpretation.mode)) == "CLARIFICATION":
        tasks = [PlanTask(
            id="t1", domain="none", action="clarify", object="none",
            fields=["other"], status="needs_clarification",
            unresolved_slots=["entity_ref"],
        )]
    tasks = _supplement_tasks_from_question(tasks, question, snapshot=snapshot)
    tasks = _drop_unrequested_rate_glossary(tasks, question)
    tasks = _drop_cross_contaminated_products(tasks, question)
    tasks = _force_heuristic_split_loans(tasks, question, snapshot=snapshot)
    tasks = _force_family_list_instead_of_portfolio(tasks, question, snapshot=snapshot)
    # Re-id estable
    for i, t in enumerate(tasks, start=1):
        t.id = f"t{i}"
    transition = _infer_transition(question, session)
    plan = TurnPlan(tasks=tasks, transition=transition, source=source)
    errors = validate_turn_plan(plan)
    if errors:
        raise InvalidTurnPlanError(errors)
    return plan


def _force_heuristic_split_loans(
    tasks: list[PlanTask],
    question: str,
    *,
    snapshot: Any | None,
) -> list[PlanTask]:
    """Personal vs hipotecario con campos distintos: prioriza el intérprete local."""
    n = _norm(question)
    if not (
        "personal" in n
        and any(s in n for s in ("hipotec", "vivienda"))
        and any(s in n for s in ("prestamo", "préstamo"))
    ):
        return tasks
    try:
        from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
        heur = interpret_turn_plan(question, None, snapshot=snapshot)
    except Exception:
        return tasks
    loan_tasks = [t for t in heur.tasks if t.object == "loan" and t.domain == "personal"]
    if not loan_tasks:
        return tasks
    others = [t for t in tasks if t.object != "loan"]
    return others + loan_tasks


def _force_family_list_instead_of_portfolio(
    tasks: list[PlanTask],
    question: str,
    *,
    snapshot: Any | None,
) -> list[PlanTask]:
    """Evita que Azure liste todo el portafolio cuando piden una sola familia."""
    n = _norm(question)
    has_portfolio = any(
        t.action == "list" or t.object == "portfolio" for t in tasks
    )
    if not has_portfolio:
        return tasks
    family = None
    fields = ["rate", "maturity", "principal", "interest_amount"]
    if any(s in n for s in ("certificado", "dap", "deposito a plazo", "depósito a plazo")) and not any(
        s in n for s in ("producto", "portafolio", "tarjeta", "prestamo", "préstamo", "cuenta")
    ):
        family = "term_deposit"
    elif any(s in n for s in ("tarjeta",)) and not any(
        s in n for s in ("producto", "portafolio", "prestamo", "préstamo", "cuenta", "certificado")
    ):
        family = "credit_card"
        fields = ["detail"]
    elif any(s in n for s in ("prestamo", "préstamo")) and not any(
        s in n for s in ("producto", "portafolio", "tarjeta", "cuenta", "certificado")
    ):
        family = "loan"
        fields = ["detail"]
    if not family:
        return tasks
    kept = [t for t in tasks if not (t.action == "list" or t.object == "portfolio")]
    kept.append(PlanTask(
        id="t_family", domain="personal", action="read_field",
        object=family, fields=fields, cardinality="all", status="ready",
    ))
    return kept


def _drop_cross_contaminated_products(tasks: list[PlanTask], question: str) -> list[PlanTask]:
    """Si la pregunta es solo préstamo/cuenta, elimina tareas TC arrastradas por el modelo."""
    n = _norm(question)
    mentions_card = _has_token(n, "visa") or _has_token(n, "mastercard") or any(
        s in n for s in ("tarjeta", "tc ")
    ) or n.endswith(" tc")
    mentions_loan = any(s in n for s in ("prestamo", "préstamo")) or (
        "cuota" in n and not mentions_card
    )
    mentions_account = any(s in n for s in ("cuenta", "ahorros", "ahorro", "corriente"))
    mentions_dap = any(s in n for s in ("certificado", "dap", "deposito", "depósito"))
    if mentions_loan and not mentions_card:
        tasks = [t for t in tasks if t.object != "credit_card"]
    if mentions_account and not mentions_card and not mentions_loan:
        tasks = [t for t in tasks if t.object != "credit_card"]
    if mentions_dap and not mentions_card and "catalog" not in {t.domain for t in tasks if t.action == "compare"}:
        # Comparación personal de DAP: quitar compare de catálogo vacío
        tasks = [
            t for t in tasks
            if not (
                t.domain == "catalog"
                and t.action == "compare"
                and not (t.filters or {}).get("compare_set")
            )
        ]
    return tasks


def _drop_unrequested_rate_glossary(tasks: list[PlanTask], question: str) -> list[PlanTask]:
    """Tasa de un producto concreto no incluye la definición del glosario.

    «cuál es la tasa de interés de la tarjeta joven» es dato personal.
    «qué es / qué significa la tasa» sí conserva el glosario.
    """
    if _wants_rate_definition(question):
        return tasks
    n = _norm(question)
    if "tasa" not in n:
        return tasks
    personal = any(
        s in n
        for s in (
            "tarjeta", "visa", "mastercard", "prestamo", "préstamo",
            "certificado", "dap", "deposito", "depósito",
            "mi tasa", "de mi", "de la", "del ",
        )
    )
    if not personal:
        return tasks
    return [
        t for t in tasks
        if not (
            t.domain == "institutional"
            and t.object == "glossary"
            and "interest_rate" in (t.fields or [])
        )
    ]


_SPEC_TO_PLAN_FIELD = {
    "payment_due_date": "due_date",
    "cutoff_date": "cutoff",
    "available_balance": "available",
    "minimum_payment": "min_payment",
    "payoff_amount": "payoff",
    "maturity_date": "maturity",
    "card_expiry": "expiry",
    "rate": "rate",
    "balance": "balance",
    "installment_amount": "installment_amount",
    "principal": "principal",
    "overdue": "overdue",
    "credit_limit": "limit",
    "movements": "movements",
}


def _pending_action_as_tasks(session: Any | None) -> list[dict]:
    """Si el fastpath dejó pending_action sin pending_tasks, reconstruir el campo."""
    pa = getattr(session, "pending_action", None) if session is not None else None
    if pa is None:
        return []
    missing = getattr(pa, "missing_requirements", None) or []
    if "account_ref" not in missing:
        return []
    spec = getattr(pa, "query_spec", None) or {}
    intent = str(getattr(pa, "intent_id", "") or "")
    field = _SPEC_TO_PLAN_FIELD.get(str(spec.get("field") or ""))
    if not field and intent == "PAYMENT_DATE_READ":
        field = "due_date"
    if not field:
        field = "balance"
    obj = {
        "PAYMENT_DATE_READ": "product",
        "LOAN_DETAIL_READ": "loan",
        "CREDIT_CARD_DETAIL_READ": "credit_card",
        "ACCOUNT_BALANCE_READ": "account",
        "TERM_DEPOSIT_DETAIL_READ": "term_deposit",
    }.get(intent, "product")
    return [{
        "task_id": "t1",
        "object": obj,
        "fields": [field],
        "original_question": getattr(pa, "original_question", None) or "",
        "display_order": [],
    }]


def _resolve_selection_to_product_id(
    selected: str,
    *,
    session: Any | None = None,
    snapshot: Any | None = None,
) -> str | None:
    """Mapea selected_option_ref / dígitos a product_id del pending o snapshot."""
    q = (selected or "").strip()
    if not q:
        return None
    pending = [
        pt for pt in (getattr(session, "pending_tasks", None) or [])
        if isinstance(pt, dict)
    ] if session is not None else []
    order: list[str] = []
    for pt in pending:
        order.extend(str(x) for x in (pt.get("display_order") or []))
    # Ref exacto o product_id exacto
    if q in order:
        return q
    if snapshot is not None:
        for p in getattr(snapshot, "products", ()) or ():
            if str(getattr(p, "product_id", "") or "") == q:
                return q
    # Ref de canal (TARJETA_0011) antes del match laxo por dígitos
    if snapshot is not None and ("_" in q or q.upper().startswith(("PRESTAMO", "TARJETA", "CUENTA", "DEPOSITO"))):
        try:
            from genesis_cognitive.context.app_channel import build_option_ref
            for p in getattr(snapshot, "products", ()) or ():
                if build_option_ref(p) == q:
                    return str(p.product_id)
        except Exception:
            pass
    # Dígitos del ref APK (PRESTAMO_27615 → 27615) o máscara de tarjeta (••••8891)
    digits = re.findall(r"\d{3,}", q)
    dig = digits[-1] if digits else ""
    candidates = list(order)
    if snapshot is not None and not candidates:
        candidates = [
            str(p.product_id)
            for p in getattr(snapshot, "products", ()) or ()
            if str(getattr(p, "status", "")).lower() == "active"
        ]
    if dig:
        # Preferir last_four / card_mask (••••2240) sobre product_id (…0868)
        if snapshot is not None:
            for p in getattr(snapshot, "products", ()) or ():
                pid = str(getattr(p, "product_id", "") or "")
                last4 = str(getattr(p, "last_four", "") or "")
                mask = "".join(ch for ch in str(getattr(p, "card_mask", "") or "") if ch.isdigit())
                if last4 == dig[-4:] or (mask and mask.endswith(dig[-4:])):
                    return pid
        for pid in candidates:
            if pid.endswith(dig) or dig in pid:
                return pid
        if snapshot is not None:
            for p in getattr(snapshot, "products", ()) or ():
                pid = str(getattr(p, "product_id", "") or "")
                if pid.endswith(dig) or dig in pid:
                    return pid
    # Prefijo APK sin match exacto: comparar build_option_ref
    if snapshot is not None and ("_" in q or q.upper().startswith(("PRESTAMO", "TARJETA", "CUENTA", "DEPOSITO"))):
        try:
            from genesis_cognitive.context.app_channel import build_option_ref
            for p in getattr(snapshot, "products", ()) or ():
                if build_option_ref(p) == q or build_option_ref(p).endswith(dig or "___"):
                    return str(p.product_id)
        except Exception:
            pass
    return None


def _pending_from_prior_question(
    session: Any,
    *,
    snapshot: Any | None,
    resolved_id: str,
) -> list[dict]:
    """Si el pending se limpió tras la 1ª card, reconstruir campos desde historial."""
    try:
        from genesis_cognitive.brain.plan_interpreter import (
            interpret_turn_plan,
            prior_personal_question,
        )
    except Exception:
        return []
    prev = prior_personal_question(session)
    if not prev:
        return []
    prior = interpret_turn_plan(prev, None, snapshot=snapshot)
    fields: list[str] = []
    obj = "credit_card"
    for t in prior.tasks:
        if t.domain != "personal" or t.action != "read_field":
            continue
        if t.object in ("loan", "account", "credit_card", "term_deposit", "product"):
            obj = t.object if t.object != "product" else obj
        for fld in t.fields or []:
            if fld not in fields and fld not in ("list", "presence", "features", "count", "movements"):
                fields.append(fld)
    if not fields:
        return []
    if snapshot is not None:
        hit = next(
            (p for p in getattr(snapshot, "products", ()) or () if str(p.product_id) == resolved_id),
            None,
        )
        if hit is not None:
            obj = {
                "LOAN": "loan",
                "TERM_DEPOSIT": "term_deposit",
                "CREDIT_CARD": "credit_card",
                "SAVINGS": "account",
                "CHECKING": "account",
                "PAYROLL": "account",
            }.get(str(hit.product_type), obj)
    return [{
        "task_id": "t1",
        "object": obj,
        "fields": fields,
        "original_question": prev,
        "display_order": [],
    }]


def plan_from_pending_selection(
    *,
    selected_ref: str,
    session: Any,
    question: str,
    snapshot: Any | None = None,
) -> TurnPlan | None:
    """Reanuda el plan persistido tras una selección inequívoca de producto."""
    pending = [
        pt for pt in (getattr(session, "pending_tasks", None) or [])
        if isinstance(pt, dict)
    ]
    if not pending:
        pending = _pending_action_as_tasks(session)
    resolved = _resolve_selection_to_product_id(
        selected_ref, session=session, snapshot=snapshot,
    )
    if not resolved:
        # También aceptar product_id crudo / ref si ya es inequívoco
        cand = (selected_ref or "").strip()
        if snapshot is not None and any(
            str(p.product_id) == cand for p in getattr(snapshot, "products", ()) or ()
        ):
            resolved = cand
    if not resolved:
        return None
    if not pending:
        pending = _pending_from_prior_question(
            session, snapshot=snapshot, resolved_id=resolved,
        )
    if not pending:
        return None
    ref = resolved
    # Tipo real del producto seleccionado (puede mezclar préstamos/DAP/tarjetas)
    obj_from_snap = None
    if snapshot is not None:
        hit = next(
            (p for p in getattr(snapshot, "products", ()) or () if str(p.product_id) == ref),
            None,
        )
        if hit is not None:
            obj_from_snap = {
                "LOAN": "loan",
                "TERM_DEPOSIT": "term_deposit",
                "CREDIT_CARD": "credit_card",
                "SAVINGS": "account",
                "CHECKING": "account",
                "PAYROLL": "account",
            }.get(str(hit.product_type))

    # Pregunta compuesta multi-familia: rearmar plan completo y anclar solo la familia pendiente
    orig = ""
    for pt in pending:
        oq = str(pt.get("original_question") or "").strip()
        if len(oq) > len(orig):
            orig = oq
    n_orig = _norm(orig or question)
    multi_family_orig = sum(
        1
        for flag in (
            any(s in n_orig for s in ("cuenta", "ahorros", "ahorro", "corriente")),
            any(s in n_orig for s in ("tarjeta", "visa", "mastercard")),
            any(s in n_orig for s in ("prestamo", "préstamo")),
            any(s in n_orig for s in ("certificado", "dap", "deposito", "depósito")),
        )
        if flag
    ) >= 2
    if multi_family_orig and orig:
        try:
            from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
            full = interpret_turn_plan(orig, None, snapshot=snapshot)
            tasks: list[PlanTask] = []
            for t in full.tasks:
                if t.domain != "personal":
                    tasks.append(t)
                    continue
                nt = PlanTask(
                    id=t.id,
                    domain=t.domain,
                    action=t.action,
                    object=t.object,
                    fields=list(t.fields or []),
                    cardinality=t.cardinality,
                    entity_ref=t.entity_ref,
                    status="ready",
                    unresolved_slots=[],
                    filters=dict(t.filters or {}),
                    exclusions=list(t.exclusions or []),
                )
                # Anclar la familia del producto seleccionado
                if obj_from_snap and t.object == obj_from_snap:
                    nt.entity_ref = ref
                    nt.status = "ready"
                    nt.unresolved_slots = []
                elif t.status == "needs_clarification" and t.object != obj_from_snap:
                    # Otras familias: si hay un solo producto, resolver; si no, listar all
                    nt.status = "ready"
                    nt.cardinality = "all" if not t.entity_ref else t.cardinality
                    nt.unresolved_slots = []
                tasks.append(nt)
            if tasks:
                for i, t in enumerate(tasks, start=1):
                    t.id = f"t{i}"
                return TurnPlan(tasks=tasks, transition="continue", source="shortcut:pending_multi_resume")
        except Exception:
            pass

    tasks = []
    for i, pt in enumerate(pending, start=1):
        obj = obj_from_snap or str(pt.get("object") or "loan")
        if obj == "product" and obj_from_snap:
            obj = obj_from_snap
        fields = list(pt.get("fields") or ["rate"])
        tasks.append(PlanTask(
            id=str(pt.get("task_id") or f"t{i}"),
            domain="personal",
            action="read_field",
            object=obj,
            fields=fields,
            entity_ref=ref if obj in ("loan", "account", "credit_card", "term_deposit") else None,
            status="ready",
        ))
    # Conservar tareas institucionales ya pendientes en historial de sesión no aplica;
    # si el original_question pedía definición, reponerla
    for fld in _institutional_fields_from_question(orig or question):
        if fld == "interest_rate":
            tasks.append(PlanTask(
                id=f"t{len(tasks)+1}", domain="institutional", action="define",
                object="glossary", fields=["interest_rate"], status="ready",
            ))
        elif fld in ("mision", "vision"):
            tasks.append(PlanTask(
                id=f"t{len(tasks)+1}", domain="institutional", action="define",
                object="bank", fields=[fld], status="ready",
            ))
    # transition=continue: no borrar pending multi-opción (otras cards siguen seleccionables)
    return TurnPlan(tasks=tasks, transition="continue", source="shortcut:pending_resume")


def is_unequivocal_structured_shortcut(
    question: str,
    session: Any | None,
    *,
    snapshot: Any | None = None,
) -> tuple[bool, str]:
    """Atajos solo si cubren TODA la solicitud (UI / selección estructurada).

    No habilitar por encontrar «misión», «disponible» o «segunda» en una
    pregunta compuesta.
    """
    q = (question or "").strip()
    n = _norm(q)
    if not n:
        return False, "empty"
    if re.fullmatch(r"\d{1,2}", n) or re.fullmatch(r"opcion\s+\d{1,2}", n):
        if session is not None and (
            getattr(session, "pending_action", None) or getattr(session, "pending_tasks", None)
        ):
            return True, "structured_option_index"
    # Conteo de productos propios: no depende del modelo
    if re.search(r"\bcuant[oa]s\b", n) and any(
        s in n for s in ("prestamo", "tarjeta", "cuenta", "certificado", "producto")
    ) and not any(s in n for s in ("dias", "meses", "puntos")):
        return True, "product_count"
    # Conocimiento inequívoco P0 (Joven / reclamación / fallecidos)
    if "joven" in n and any(s in n for s in ("caracter", "dirigida", "que es", "informacion")):
        return True, "kb_joven"
    if "reclam" in n and not any(s in n for s in ("debo", "saldo", "disponible", "cuota")):
        return True, "kb_reclamacion"
    if "fallec" in n or "de cujus" in n:
        return True, "kb_fallecidos"
    # Glosario / mixta definición+personal — antes de compound_personal
    _is_avail_glossary = bool(
        re.search(r"(que|qué)\s+(significa|es)\s+(el\s+)?saldo\s+disponible", n)
        or re.search(r"definici[oó]n\s+(del?\s+)?saldo\s+disponible", n)
    )
    _mixed_personal = any(
        s in n
        for s in (
            "cuanto tengo", "cuánto tengo", "y cuanto", "y cuánto",
            "mi saldo", "de mi cuenta", "en ahorros", "en mi",
        )
    )
    if _is_avail_glossary and _mixed_personal:
        return False, "open_mixed_glossary_personal"
    if _is_avail_glossary:
        return True, "kb_glossary_available"
    # Institucional puro (misión/visión/valores): no abrir azure resolve_full
    # cuando el plan local + FAQ/Search ya cubren la familia de capacidad.
    inst_fields = _institutional_fields_from_question(n)
    if inst_fields and not any(
        s in n
        for s in (
            "saldo", "debo", "cuota", "disponible", "prestamo", "préstamo",
            "tarjeta", "cuenta", "productos", "tengo", "adeud", "pago",
            "certificado", "deposito", "depósito",
        )
    ):
        return True, "kb_institutional"
    # Ref APK / selección de card ANTES del import de field_guardrails (compound)
    if session is not None:
        has_pending_early = bool(
            getattr(session, "pending_tasks", None) or _pending_action_as_tasks(session)
        )
        pending_early = [
            pt for pt in (session.pending_tasks or []) if isinstance(pt, dict)
        ] if has_pending_early else []
        for pt in pending_early:
            order = list(pt.get("display_order") or [])
            if q in order or any(q == str(x) for x in order):
                return True, "structured_product_ref"
            if len(q) >= 4 and any(q in str(x) or str(x) in q for x in order):
                return True, "structured_product_ref"
        resolved_early = _resolve_selection_to_product_id(q, session=session, snapshot=snapshot)
        if resolved_early and has_pending_early:
            return True, "structured_product_ref"
        if resolved_early or re.match(
            r"^(tarjeta|prestamo|cuenta|deposito)_\d+",
            n,
            flags=re.IGNORECASE,
        ):
            try:
                from genesis_cognitive.brain.plan_interpreter import prior_personal_question as _ppq
                if _ppq(session):
                    return True, "structured_product_ref"
            except Exception:
                pass
    # Multi-campo personal de tarjeta/préstamo: plan local completo (P01/P02/P03…)
    try:
        from genesis_cognitive.router.field_guardrails import is_compound_personal_query
        if is_compound_personal_query(q):
            return True, "compound_personal_local"
    except Exception:
        if len(n) >= 25 and sum(
            1 for s in ("debo", "disponible", "fecha", "minimo", "mínimo", "saldo") if s in n
        ) >= 2:
            return True, "compound_personal_local"
    # Catálogo / procesos inequívocos (evitan Azure → NON_OPERATIONAL / glosario vacío)
    from genesis_cognitive.brain.plan_interpreter import (
        detect_catalog_refs,
        is_product_pointer,
        prior_personal_question,
    )
    catalog_refs = detect_catalog_refs(q)
    if (
        catalog_refs
        and any(s in n for s in ("que es", "que significa", "caracter", "condiciones", "requisitos"))
        and not _is_avail_glossary
    ):
        return True, "kb_catalog_define"
    if any(s in n for s in ("compara", "comparame")) or (
        "diferencia" in n and "entre" in n
    ) or any(s in n for s in ("agrega", "anade", "añade")) and (
        catalog_refs or (session is not None and getattr(session, "compare_set", None))
    ) or any(
        s in n
        for s in (
            "cual es mejor", "me conviene", "menos cargos", "mejores beneficios",
            "mas barata", "cual de las", "cual escoger", "cual tiene mejor",
            "cual tiene menos",
        )
    ):
        # Compare personal de portafolio (mis TC / mi tarjeta X con Y) ≠ catálogo KB
        _personal_cmp = any(
            s in n
            for s in (
                "mi tarjeta", "mis tarjetas", "mis certificados", "mis dap",
                "mis prestamos", "mis préstamos", "mis cuentas", "mis depositos",
                "mis depósitos", "con la tarjeta", "con mi tarjeta",
            )
        )
        if not (
            _personal_cmp
            and any(s in n for s in ("compara", "comparame", "diferencia"))
        ):
            return True, "kb_catalog_compare"
    if session is not None and getattr(session, "compare_set", None) and any(
        s in n for s in (
            "primera", "segunda", "tercera", "ultima", "último", "ultimo",
            "esta ultima", "esta última", "tienen diferente", "que tienen",
            "diferencia en", "caracteristicas", "características", "de las tres",
            "hablame", "háblame",
        )
    ):
        return True, "kb_compare_ordinal"
    if any(s in n for s in ("cargo", "cargos", "comision", "comisión")) and "tarjeta" in n and (
        "puede" in n or "tiene" in n or "que" in n
    ) and not any(s in n for s in ("me cobraron", "me cobro", "recientemente", "mi tarjeta")):
        return True, "kb_cargos"
    # Tras catálogo de cargos: historial personal / ausencia de movimientos
    if any(s in n for s in ("me cobraron", "me cobro", "recientemente", "alguno recientemente")):
        return True, "kb_movements_or_absent"
    if "cancel" in n and any(s in n for s in ("prestamo", "prestamos", "tarjeta", "producto", "funciona", "proceso", "como")):
        # Monto personal de cancelación sigue por vía abierta / personal
        if not any(s in n for s in ("cuanto", "monto", "pagar para cancelar", "cancelar el mio", "cancelar el mío")):
            return True, "kb_cancelacion"
    # Payoff personal tras proceso de cancelación
    if any(s in n for s in ("cancelar el mio", "cancelar el mío", "pagar para cancelar", "cuanto tendria que pagar", "cuánto tendría que pagar")):
        return True, "personal_payoff"
    if any(s in n for s in (
        "tengo yo ese", "tengo ese producto", "yo tengo ese", "lo tengo", "tengo yo",
    )):
        return True, "kb_existence"
    # Selección corta por nombre comercial tras clarificación («El personal.»)
    if session is not None and (
        getattr(session, "pending_tasks", None) or getattr(session, "pending_action", None)
    ) and len(n.split()) <= 4 and any(
        s in n for s in ("personal", "hipotecario", "vehicular", "multicredit", "ahorros", "corriente", "nomina")
    ):
        return True, "pending_product_name"
    if session is not None and is_product_pointer(q) and prior_personal_question(session):
        return True, "replay_prior_fields"
    from genesis_cognitive.brain.security_secrets import is_auth_secret_message
    if is_auth_secret_message(q):
        return True, "auth_secret_refuse"
    # Titularidad ajena: alinear con plan_interpreter (no solo «de mi esposo»)
    if re.search(
        r"\b(esposo|esposa|marido|mujer|hijo|hija|pareja|mama|papa|madre|padre)\b",
        n,
    ) and any(s in n for s in ("saldo", "cuenta", "disponible", "debe", "deuda", "prestamo", "tiene")):
        if not any(s in n for s in ("abro", "abrir", "requisitos", "solicitar")):
            return True, "third_party_refuse"
    # Plan heurístico personal ya cubierto (evita resolve_full → noop en QA)
    try:
        from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan

        probe = interpret_turn_plan(q, session, snapshot=snapshot)
    except Exception:
        probe = None
    if probe and probe.tasks:
        domains = {t.domain for t in probe.tasks}
        actions = {t.action for t in probe.tasks}
        ok_domain = domains <= {"personal", "none", "chitchat"}
        ok_action = actions <= {
            "read_field", "refuse", "clarify", "count", "chitchat", "list",
        }
        statuses = {t.status for t in probe.tasks}
        ok_status = statuses <= {"ready", "needs_clarification", "unsupported"}
        has_useful = any(
            (t.action == "read_field" and t.status in ("ready", "needs_clarification"))
            or t.action in ("refuse", "clarify", "count", "chitchat", "list")
            for t in probe.tasks
        )
        if ok_domain and ok_action and ok_status and has_useful:
            return True, "heuristic_personal_plan"
    return False, "open_language"
