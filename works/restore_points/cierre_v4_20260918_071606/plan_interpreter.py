"""Intérprete heurístico multi-tarea desde el mensaje completo + estado.

Produce un TurnPlan antes de que un clasificador de intención única descarte
subpreguntas. No sustituye Azure structured outputs cuando estén disponibles;
cubre el cierre local determinista exigido por V3.1.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from genesis_cognitive.brain.security_secrets import is_auth_secret_message, scan_auth_secrets
from genesis_cognitive.brain.turn_plan import PlanTask, TurnPlan, validate_turn_plan


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = "".join(
        c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn"
    )
    t = re.sub(r"[¿?¡!.,;:]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_CATALOG_ALIASES: dict[str, tuple[str, ...]] = {
    # Identidades distintas — no fusionar por similitud lingüística
    "multicredito": ("multicredito", "multi credito"),
    "credito_diferido": ("credito diferido",),
    "cuotas_bsc": ("cuotas bsc",),
    "visa_platinum": ("visa platinum", "platinum"),
    "visa_infinite": ("visa infinite", "infinite"),
    "visa_gold": ("visa gold", "gold"),
    "visa_classic": ("visa classic", "classic"),
    "visa_joven": ("visa joven", "joven"),
    "cuenta_ahorros": ("cuenta de ahorros", "cuenta ahorros"),
    "cuenta_corriente": ("cuenta corriente",),
    "cuenta_nomina": ("cuenta nomina", "cuenta nómina", "nomina", "nómina"),
    "prestamo_personal": ("prestamo personal", "préstamo personal"),
}


def detect_catalog_refs(question: str) -> list[str]:
    """Devuelve refs en orden de mención del usuario (no orden del dict de alias)."""
    q = _norm(question)
    hits: list[tuple[int, str]] = []
    for key, aliases in _CATALOG_ALIASES.items():
        best = None
        for a in aliases:
            idx = q.find(a)
            if idx >= 0 and (best is None or idx < best):
                best = idx
        if best is not None:
            hits.append((best, key))
    hits.sort(key=lambda x: x[0])
    return [k for _, k in hits]


def message_has_personal_subquery(question: str) -> bool:
    q = _norm(question)
    personal_markers = (
        "disponible", "saldo", "cuanto tengo", "cuanto debo", "deuda",
        "mi cuenta", "mi tarjeta", "mi prestamo", "mis prestamos",
        "fecha de pago", "pago minimo", "tasa de mi", "vencimiento de mi",
        "mis certificados", "certificados", "tengo yo", "tengo ese",
    )
    return any(m in q for m in personal_markers)


def message_is_institutional_only(question: str) -> bool:
    """True si la solicitud completa es institucional (sin subconsulta personal)."""
    from genesis_cognitive.brain.azure_intent_brain import _is_institutional_entity_request

    if not _is_institutional_entity_request(question):
        return False
    return not message_has_personal_subquery(question)


def _next_id(n: int) -> str:
    return f"t{n}"


def interpret_turn_plan(
    question: str,
    session: Any | None = None,
    *,
    snapshot: Any | None = None,
) -> TurnPlan:
    """Construye TurnPlan multi-tarea desde el mensaje original y el estado."""
    raw = question or ""
    q = _norm(raw)
    tasks: list[PlanTask] = []
    n = 1
    transition = "none"
    source = "heuristic_multi"

    pf = getattr(session, "product_focus", None) if session is not None else None
    focus_kind = getattr(pf, "kind", None) if pf is not None else None
    focus_id = getattr(pf, "product_id", None) if pf is not None else None

    # Follow-up comparación institucional (misión vs visión)
    if any(s in q for s in ("en que se diferencian", "en qué se diferencian", "diferencias", "diferencian")):
        topic = getattr(session, "last_knowledge_topic", None) if session else None
        if topic or any(s in q for s in ("mision", "vision", "banco")):
            tasks.append(PlanTask(
                id=_next_id(n), domain="institutional", action="compare",
                object="bank", fields=["mision", "vision"], status="ready",
            ))
            n += 1
            transition = "continue"

    # ── Historial de movimientos no soportado (con saldo sí) ──
    if any(s in q for s in ("movimientos", "ultimos movimientos", "últimos movimientos", "transacciones")):
        if any(s in q for s in ("saldo", "disponible", "cuanto tengo", "cuánto tengo", "dime mi saldo")):
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="account", fields=["available" if "disponible" in q else "balance"],
                entity_ref=focus_id if focus_kind == "ACCOUNT" else None,
                status="ready",
            ))
            n += 1
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object="account", fields=["movements"],
            status="unsupported",
        ))
        n += 1

    # ── Secretos: tarea refuse, no continuar a extracción de dígitos ──
    if is_auth_secret_message(raw):
        tasks.append(PlanTask(
            id=_next_id(n), domain="none", action="refuse", object="secret",
            fields=["auth_secret"], status="ready",
        ))
        plan = TurnPlan(tasks=tasks, transition="none", source=source)
        return plan

    # ── Titularidad ajena ──
    if re.search(
        r"\b(esposo|esposa|marido|mujer|hijo|hija|pareja|mama|papa|madre|padre)\b",
        q,
    ) and any(s in q for s in ("saldo", "cuenta", "disponible", "debe", "deuda", "prestamo")):
        # Pregunta general de proceso ("abrir cuenta para mi hijo") ≠ consulta ajena
        if any(s in q for s in ("abro", "abrir", "como abro", "requisitos", "solicitar")):
            tasks.append(PlanTask(
                id=_next_id(n), domain="process", action="process", object="account",
                fields=["open_account"], status="ready",
            ))
            n += 1
        else:
            tasks.append(PlanTask(
                id=_next_id(n), domain="none", action="refuse", object="third_party",
                fields=["ownership"], status="ready",
            ))
            plan = TurnPlan(tasks=tasks, transition="none", source=source)
            return plan

    # ── Existencia personal tras catálogo (MIX07) ──
    existence = any(
        s in q for s in (
            "tengo yo ese", "tengo ese producto", "yo tengo ese",
            "lo tengo", "tengo yo", "poseo ese",
        )
    )
    catalog_refs = detect_catalog_refs(raw)
    compare_ask = any(s in q for s in ("compara", "comparame", "diferencia entre", "vs "))
    add_to_compare = any(s in q for s in ("agrega", "añade", "anade", "incluye tambien", "incluye también"))
    remove_from_compare = any(s in q for s in ("quita", "elimina", "saca "))

    if existence:
        ref = None
        if session is not None:
            ref = getattr(session, "last_knowledge_topic", None)
            cset = getattr(session, "compare_set", None) or []
            if not ref and cset:
                ref = cset[-1]
        if catalog_refs:
            ref = catalog_refs[0]
        filters_ex: dict[str, Any] = {"catalog_ref": ref} if ref else {}
        cmap = getattr(session, "catalog_personal_map", None) if session is not None else None
        if isinstance(cmap, dict) and ref and ref in cmap:
            filters_ex["authorized_personal_id"] = cmap[ref]
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="check_existence",
            object="catalog_mapped", fields=["presence"],
            entity_ref=ref, status="ready" if ref else "needs_clarification",
            unresolved_slots=[] if ref else ["catalog_ref"],
            filters=filters_ex,
        ))
        n += 1

    # ── Comparación de catálogo (CC02/CC03) ──
    if compare_ask or add_to_compare or remove_from_compare:
        transition = "compare_expand" if add_to_compare else (
            "selection" if remove_from_compare else "none"
        )
        existing = list(getattr(session, "compare_set", None) or []) if session else []
        refs = catalog_refs or existing
        if add_to_compare and catalog_refs:
            refs = existing + [r for r in catalog_refs if r not in existing]
        if remove_from_compare and catalog_refs:
            refs = [r for r in existing if r not in catalog_refs]
        tasks.append(PlanTask(
            id=_next_id(n), domain="catalog", action="compare",
            object="product", fields=["features"], cardinality="compare",
            entity_ref=",".join(refs) if refs else None,
            filters={"compare_set": refs},
            status="ready" if len(refs) >= 2 or compare_ask else "needs_clarification",
            unresolved_slots=[] if refs else ["compare_entities"],
        ))
        n += 1

    # ── Institucional (misión / visión / valores) ──
    inst_parts: list[str] = []
    if "mision" in q:
        inst_parts.append("mision")
    if "vision" in q:
        inst_parts.append("vision")
    if "valores" in q:
        inst_parts.append("valores")
    if inst_parts:
        tasks.append(PlanTask(
            id=_next_id(n), domain="institutional", action="define",
            object="bank", fields=inst_parts, scope="institutional", status="ready",
        ))
        n += 1
        if session is not None and getattr(session, "pending_action", None) is not None:
            transition = "topic_change"

    # ── Definición / proceso de catálogo (CD13, GR02) — sin producto personal ──
    if any(s in q for s in ("pago minimo", "que es el pago minimo", "significa pago minimo")):
        if "mi tarjeta" not in q and "de mi" not in q:
            tasks.append(PlanTask(
                id=_next_id(n), domain="catalog", action="define",
                object="credit_card", fields=["min_payment"], status="ready",
            ))
            n += 1
    if any(s in q for s in ("cancelar tarjeta", "cancelacion de tarjeta", "cancelación de tarjeta")) and (
        "compara" in q or "prestamo" in q or "préstamo" in q or "proceso" in q
    ):
        tasks.append(PlanTask(
            id=_next_id(n), domain="process", action="compare",
            object="cancellation", fields=["process"], cardinality="compare",
            filters={"entities": ["credit_card", "loan"]},
            status="ready",
        ))
        n += 1
    elif any(s in q for s in (
        "como cancelo", "cómo cancelo", "proceso de cancelacion", "proceso de cancelación",
        "cancelar una tarjeta", "cancelar un prestamo", "cancelar un préstamo",
        "proceso de cancelar", "es igual al de",
    )):
        if "igual" in q or "compara" in q or ("tarjeta" in q and "prestamo" in q):
            tasks.append(PlanTask(
                id=_next_id(n), domain="process", action="compare",
                object="cancellation", fields=["process"], cardinality="compare",
                filters={"entities": ["credit_card", "loan"]},
                status="ready",
            ))
            n += 1
        elif "mi " not in q or "monto" not in q:
            tasks.append(PlanTask(
                id=_next_id(n), domain="process", action="process",
                object="cancellation", fields=["process"], status="ready",
            ))
            n += 1

    # ── Definición de saldo disponible (conocimiento) ──
    if any(s in q for s in ("que significa saldo disponible", "qué significa saldo disponible",
                             "que es saldo disponible", "qué es el saldo disponible")):
        tasks.append(PlanTask(
            id=_next_id(n), domain="institutional", action="define",
            object="glossary", fields=["available_balance"], status="ready",
        ))
        n += 1

    # ── Personal: liquidez / saldo ──
    wants_available = "disponible" in q and "significa" not in q and "que es" not in q and "qué es" not in q
    wants_current = any(s in q for s in ("saldo actual", "balance actual", "saldo contable"))
    wants_balance = wants_current or (
        "saldo" in q and not wants_available and "significa" not in q
    )
    mentions_card = any(s in q for s in ("tarjeta", "visa", "mastercard", "tc "))
    mentions_account = any(s in q for s in ("cuenta", "ahorros", "corriente"))
    mentions_loan = any(s in q for s in ("prestamo", "préstamo", "cuota"))
    mentions_dap = any(s in q for s in ("certificado", "dap", "deposito a plazo", "depósito a plazo", "mis certificados"))

    # Typos frecuentes (X01 / V3-19)
    typo_debt = bool(re.search(r"\b(debo|deuda|adeud|k debo|e k debo)\b", q)) or "debo" in q.replace(" ", "")
    typo_pay = any(s in q for s in (
        "cuando me toca pagar", "cuando pago", "cuándo pago", "fecha de pago",
        "tocar pagar", "cuando debo pagar", "debo pagar",
    ))

    # ── Definición de tasa + tasa personal (V3-20) ──
    if "tasa" in q and any(s in q for s in ("significa", "que es", "qué es", "definicion", "definición")):
        tasks.append(PlanTask(
            id=_next_id(n), domain="institutional", action="define",
            object="glossary", fields=["interest_rate"], status="ready",
        ))
        n += 1
        if any(s in q for s in ("mi prestamo", "mi préstamo", "prestamo", "préstamo")):
            loans = []
            if snapshot is not None:
                loans = [
                    p for p in snapshot.products
                    if p.product_type == "LOAN" and str(p.status).lower() == "active"
                ]
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="loan", fields=["rate"],
                status="needs_clarification" if len(loans) != 1 else "ready",
                entity_ref=loans[0].product_id if len(loans) == 1 else None,
                unresolved_slots=["entity_ref"] if len(loans) != 1 else [],
            ))
            n += 1

    # ── Disponible multi-moneda / total (V3-22) ──
    if any(s in q for s in ("todas mis cuentas", "el total", "disponible en todas")):
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object="account", fields=["available"], cardinality="all",
            filters={"multi_currency": True, "no_mixed_total": True},
            status="ready",
        ))
        n += 1

    pf = getattr(session, "product_focus", None) if session is not None else None
    focus_kind = getattr(pf, "kind", None) if pf is not None else None
    focus_id = getattr(pf, "product_id", None) if pf is not None else None

    # Corrección explícita de producto — sustituye foco/tareas previas (no acumula)
    if any(s in q for s in ("no la", "no, la", "no, me", "me referia", "me refería", "la corriente", "la de ahorros", "la otra")):
        transition = "correction"
        # Invalidar pendiente/foco previos en el plan (el caller aplica al estado)
        filters_corr: dict[str, Any] = {"invalidate_prior_focus": True}
        obj = "account"
        if "corriente" in q:
            filters_corr["account_subtype"] = "CHECKING"
        elif "ahorros" in q:
            filters_corr["account_subtype"] = "SAVINGS"
        elif "nomina" in q or "nómina" in q:
            filters_corr["account_subtype"] = "PAYROLL"
        else:
            filters_corr["deictic"] = "other"
        field = "balance" if ("saldo actual" in q or ("actual" in q and "disponible" not in q)) else (
            "available" if wants_available else "balance"
        )
        entity = None
        want_type = filters_corr.get("account_subtype")
        if snapshot is not None and want_type:
            for p in snapshot.products:
                if p.product_type == want_type and str(p.status).lower() == "active":
                    entity = p.product_id
                    break
        # Una sola tarea de corrección — no añadir lecturas del foco anterior
        tasks.clear()
        n = 1
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object=obj, fields=[field],
            filters=filters_corr, entity_ref=entity, status="ready",
        ))
        n += 1
        plan = TurnPlan(tasks=tasks, transition="correction", source=source)
        errors = validate_turn_plan(plan)
        if errors:
            from genesis_cognitive.brain.turn_plan import InvalidTurnPlanError
            raise InvalidTurnPlanError(errors)
        return plan

    # Multi-campo tarjeta (P01): deuda + disponible + fecha
    card_fields: list[str] = []
    if mentions_card or focus_kind == "CARD" or (typo_debt and "tarjeta" in q):
        if typo_debt or any(s in q for s in ("debo", "deuda", "adeudado", "cuanto debo", "cuánto debo")):
            card_fields.append("balance")
        if wants_available or "disponible" in q:
            card_fields.append("available")
        if typo_pay or any(s in q for s in (
            "fecha de pago", "cuando pago", "cuándo pago", "tocar pagar",
            "cuando me toca", "cuando debo pagar", "debo pagar", "cuando pagar",
        )):
            if "pago minimo" not in q:
                card_fields.append("due_date")
        if any(s in q for s in ("pago minimo", "mínimo", "minimo")) and "significa" not in q:
            card_fields.append("min_payment")

    # Dígitos explícitos — saltar si el mensaje es marco de secreto (ya manejado arriba)
    digit_hints = re.findall(r"\d{4,}", raw)
    digit_entity = None
    if snapshot is not None and digit_hints:
        for p in getattr(snapshot, "products", ()) or ():
            pid = str(getattr(p, "product_id", "") or "")
            last4 = str(getattr(p, "last_four", "") or "")
            for d in digit_hints:
                if pid.endswith(d) or last4 == d[-4:]:
                    digit_entity = pid
                    break
            if digit_entity:
                break

    if len(card_fields) >= 2 or (mentions_card and card_fields) or (typo_debt and card_fields):
        status = "ready"
        unresolved: list[str] = []
        entity = digit_entity or (focus_id if focus_kind == "CARD" else None)
        # Contar tarjetas en snapshot
        cards = []
        if snapshot is not None:
            cards = [
                p for p in getattr(snapshot, "products", ()) or ()
                if getattr(p, "product_type", "") == "CREDIT_CARD"
                and str(getattr(p, "status", "")).lower() == "active"
            ]
        if entity is None and len(cards) != 1:
            if len(cards) > 1:
                status = "needs_clarification"
                unresolved = ["entity_ref"]
            elif len(cards) == 1:
                entity = cards[0].product_id
        elif entity is None and len(cards) == 1:
            entity = cards[0].product_id
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object="credit_card", fields=card_fields or ["available"],
            cardinality="single", entity_ref=entity,
            status=status, unresolved_slots=unresolved,
        ))
        n += 1
    elif wants_available or wants_balance:
        # Resolver objeto: mención explícita > foco > account por liquidez
        if mentions_card and not mentions_account:
            obj = "credit_card"
            entity = focus_id if focus_kind == "CARD" else None
        elif mentions_account:
            obj = "account"
            entity = focus_id if focus_kind == "ACCOUNT" else None
        elif focus_kind == "CARD" and not mentions_account:
            obj = "credit_card"
            entity = focus_id
        elif mentions_loan and "disponible" in q:
            # Disponible de préstamo: no convertir a cuenta
            obj = "loan"
            entity = focus_id if focus_kind == "LOAN" else None
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object=obj, fields=["available"], entity_ref=entity,
                status="unsupported",  # si no hay campo real
            ))
            n += 1
            obj = None  # ya añadido
        else:
            obj = "account"
            entity = focus_id if focus_kind == "ACCOUNT" else None
        if obj:
            # Ambos campos cuando se piden juntos (V3-08: actual + disponible)
            if wants_current and wants_available:
                fields_acc = ["balance", "available"]
            elif wants_current:
                fields_acc = ["balance"]
            elif wants_available:
                fields_acc = ["available"]
            else:
                fields_acc = ["balance"]
            # Ambigüedad cuenta+tarjeta elegibles sin foco
            ambiguous = False
            if snapshot is not None and entity is None and not mentions_card and not mentions_account:
                accts = [
                    p for p in getattr(snapshot, "products", ()) or ()
                    if getattr(p, "product_type", "") in ("SAVINGS", "CHECKING", "PAYROLL")
                    and str(getattr(p, "status", "")).lower() == "active"
                ]
                cards = [
                    p for p in getattr(snapshot, "products", ()) or ()
                    if getattr(p, "product_type", "") == "CREDIT_CARD"
                    and str(getattr(p, "status", "")).lower() == "active"
                ]
                if accts and cards and focus_kind not in ("ACCOUNT", "CARD"):
                    ambiguous = True
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object=obj, fields=fields_acc, entity_ref=entity,
                status="needs_clarification" if ambiguous else "ready",
                unresolved_slots=["entity_ref"] if ambiguous else [],
            ))
            n += 1

    # ── Certificados / DAPs (P15) ──
    if mentions_dap or any(s in q for s in ("mis certificados", "todos los certificados")):
        fields: list[str] = []
        if "tasa" in q:
            fields.append("rate")
        if any(s in q for s in ("vence", "vencimiento")):
            fields.append("maturity")
        if not fields:
            fields = ["rate", "maturity"]
        excl: list[str] = []
        if any(s in q for s in (
            "no el balance", "sin balance", "no el capital", "sin capital", "pero no",
            "no muestres", "no mostrar", "sin mostrar",
        )):
            excl = ["balance", "capital", "principal"]
        card = "all"
        if any(s in q for s in ("primero en vencer", "vence primero", "mas pronto", "más pronto")):
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="term_deposit", fields=fields, cardinality="all",
                exclusions=excl, status="ready",
            ))
            n += 1
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="compare",
                object="term_deposit", fields=["maturity"], cardinality="all",
                filters={"operator": "earliest"}, exclusions=excl,
                depends_on=[f"t{n-1}"], status="ready",
            ))
            n += 1
        else:
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="term_deposit", fields=fields, cardinality=card,
                exclusions=excl, status="ready",
            ))
            n += 1

    # ── Ordinal / foco sobre compare_set de catálogo ──
    if session is not None and any(s in q for s in (
        "la segunda", "el segundo", "la primera", "el primero", "la tercera",
        "quedate", "quédate", "quedate con", "requisitos", "diferenc",
    )):
        cset = list(getattr(session, "compare_set", None) or [])
        if cset and (
            "de las" in q or "de los" in q or "hablame" in q or "háblame" in q
            or "solo de" in q or "compar" in q or "quedate" in q or "quédate" in q
            or "requisitos" in q or "diferenc" in q or len(cset) >= 2
        ) and not any(s in q for s in ("prestamo", "préstamo", "tarjeta", "retomando")):
            # Pedir diferencias del conjunto vigente (sin ordinal)
            if any(s in q for s in ("requisitos", "diferenc", "distint")) and not any(
                s in q for s in ("primer", "segund", "tercer")
            ):
                tasks.append(PlanTask(
                    id=_next_id(n), domain="catalog", action="compare",
                    object="product", fields=["features", "requirements"],
                    cardinality="compare",
                    entity_ref=",".join(cset),
                    filters={"compare_set": cset, "facet": "requirements"},
                    status="ready",
                ))
                n += 1
                transition = "continue"
            else:
                ordinal = 2 if "segund" in q else (1 if "primer" in q else (3 if "tercer" in q else None))
                if ordinal and 1 <= ordinal <= len(cset):
                    chosen = cset[ordinal - 1]
                    tasks.append(PlanTask(
                        id=_next_id(n), domain="catalog", action="define",
                        object=chosen, fields=["info"], entity_ref=chosen,
                        filters={"ordinal": ordinal, "compare_set": cset},
                        status="ready",
                    ))
                    n += 1
                    transition = "selection"

    # ── Retomar pendiente tras excursión institucional / selección ordinal ──
    if any(s in q for s in (
        "retomando", "volviendo al", "siguiendo con",
        "el segundo", "la segunda", "el primero", "la primera",
        "la tarjeta que mostraste",
    )):
        transition = "continue" if transition == "none" else transition
        pending_list = list(getattr(session, "pending_tasks", None) or []) if session else []
        pa = getattr(session, "pending_action", None) if session else None
        display_order = list((getattr(session, "compare_set", None) or [])) if session else []
        # Orden de display de productos personales en pending
        if session is not None and getattr(session, "pending_tasks", None):
            for pt in session.pending_tasks:
                if pt.get("display_order"):
                    display_order = list(pt["display_order"])
                    break
        if pending_list or pa is not None:
            ordinal = None
            if "primer" in q or re.search(r"\b1\b", q):
                ordinal = 1
            elif "segund" in q or re.search(r"\b2\b", q):
                ordinal = 2
            elif "tercer" in q or re.search(r"\b3\b", q):
                ordinal = 3
            entity = None
            if ordinal and snapshot is not None:
                # Preferir tarjetas si el pendiente es de tarjeta
                obj_hint = (pending_list[0].get("object") if pending_list else None) or ""
                if "LOAN" in ((pa.intent_id if pa else "") or "") or obj_hint == "loan":
                    pool = [
                        p for p in snapshot.products
                        if p.product_type == "LOAN" and str(p.status).lower() == "active"
                    ]
                elif obj_hint == "credit_card" or "CARD" in ((pa.intent_id if pa else "") or ""):
                    pool = [
                        p for p in snapshot.products
                        if p.product_type == "CREDIT_CARD" and str(p.status).lower() == "active"
                    ]
                else:
                    pool = [
                        p for p in snapshot.products
                        if str(p.status).lower() == "active"
                    ]
                if display_order:
                    # Mapear IDs del display_order al pool
                    by_id = {p.product_id: p for p in pool}
                    ordered = [by_id[i] for i in display_order if i in by_id]
                    if ordered:
                        pool = ordered
                if 1 <= ordinal <= len(pool):
                    entity = pool[ordinal - 1].product_id
            fields = list(pending_list[0].get("fields") or []) if pending_list else []
            exclusions = list(pending_list[0].get("exclusions") or []) if pending_list else []
            obj = (pending_list[0].get("object") if pending_list else None) or (
                "loan" if pa and "LOAN" in (pa.intent_id or "") else "credit_card"
            )
            # Conservar TODOS los campos pendientes; no sustituir por rate/available
            if not fields:
                oq = ""
                if pending_list:
                    oq = str(pending_list[0].get("original_question") or "")
                if pa is not None:
                    oq = oq or (pa.original_question or "")
                oq_l = oq.lower()
                if "tasa" in oq_l:
                    fields = ["rate"]
                elif "disponible" in oq_l and ("deuda" in oq_l or "debo" in oq_l):
                    fields = ["balance", "available"]
                elif "disponible" in oq_l:
                    fields = ["available"]
                else:
                    fields = ["balance"]
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object=obj,
                fields=list(fields),
                exclusions=list(exclusions),
                entity_ref=entity,
                filters={
                    **(dict(pending_list[0].get("filters") or {}) if pending_list else {}),
                    **({"ordinal": ordinal} if ordinal else {}),
                },
                status="ready" if entity else "needs_clarification",
                unresolved_slots=[] if entity else ["entity_ref"],
            ))
            n += 1
            # Marcar pendientes como en resolución (el executor cierra por ID)
            transition = "selection" if entity else "continue"

    # ── Catálogo info sin comparación (si solo mencionan producto de catálogo) ──
    if catalog_refs and not existence and not compare_ask and not add_to_compare:
        if not any(t.domain == "catalog" for t in tasks):
            # Solo si no hay ya personal dominante sin “qué es”
            if any(s in q for s in ("que es", "qué es", "condiciones", "requisitos", "informacion", "información")):
                tasks.append(PlanTask(
                    id=_next_id(n), domain="catalog", action="define",
                    object=catalog_refs[0], fields=["info"], status="ready",
                    entity_ref=catalog_refs[0],
                ))
                n += 1

    # Fallback: una tarea via adaptador de IntentPacket
    if not tasks:
        from genesis_cognitive.brain.azure_intent_brain import heuristic_intent
        from genesis_cognitive.brain.turn_plan import intent_packet_to_turn_plan

        pkt = heuristic_intent(raw, session)
        plan = intent_packet_to_turn_plan(pkt)
        plan.source = "adapter"
        return plan

    plan = TurnPlan(tasks=tasks, transition=transition, source=source)
    errors = validate_turn_plan(plan)
    if errors:
        from genesis_cognitive.brain.turn_plan import InvalidTurnPlanError

        raise InvalidTurnPlanError(errors)
    return plan


def scrub_inbound_question(question: str) -> tuple[str, dict[str, Any]]:
    """Depura secretos antes de historial / modelo. Devuelve (texto_seguro, meta)."""
    from genesis_cognitive.brain.security_secrets import redact_secret_digits_for_logs

    scan = scan_auth_secrets(question or "")
    safe = redact_secret_digits_for_logs(question or "")
    meta = {
        "had_secret_frame": scan.has_secret_frame,
        "blocked_digit_match": scan.should_block_product_digit_match,
        "digit_count": len(scan.digits),
    }
    return safe, meta
