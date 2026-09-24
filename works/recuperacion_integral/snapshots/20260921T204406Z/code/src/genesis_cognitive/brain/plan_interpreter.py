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
    "cuenta_ahorros": ("cuenta de ahorros", "cuenta ahorros", "cuenta de ahorro", "de ahorros"),
    "cuenta_corriente": ("cuenta corriente",),
    "cuenta_nomina": ("cuenta nomina", "cuenta nómina", "nomina", "nómina"),
    "prestamo_personal": ("prestamo personal", "préstamo personal"),
}

_TYPE_TO_OBJECT: dict[str, str] = {
    "LOAN": "loan",
    "TERM_DEPOSIT": "term_deposit",
    "CREDIT_CARD": "credit_card",
    "SAVINGS": "account",
    "CHECKING": "account",
    "PAYROLL": "account",
}


def _active_products(snapshot: Any) -> list[Any]:
    if snapshot is None:
        return []
    return [
        p for p in getattr(snapshot, "products", ()) or ()
        if str(getattr(p, "status", "")).lower() == "active"
    ]


def _product_bears_rate(product: Any) -> bool:
    """True si el producto del portafolio puede responder una consulta de tasa."""
    pt = str(getattr(product, "product_type", "") or "")
    if pt == "LOAN":
        return True
    if pt == "TERM_DEPOSIT":
        return True
    if pt == "CREDIT_CARD":
        return getattr(product, "interest_rate", None) is not None
    return False


def _product_bears_maturity(product: Any) -> bool:
    pt = str(getattr(product, "product_type", "") or "")
    if pt == "TERM_DEPOSIT":
        return True
    if pt == "LOAN":
        return True
    return getattr(product, "maturity_date", None) is not None


def is_product_pointer(question: str) -> bool:
    """«dame la de multicrédito»: cambia de producto sin pedir un campo nuevo."""
    q = _norm(question)
    if not q:
        return False
    if any(s in q for s in (
        "cuanto", "cuando", "fecha", "tasa", "saldo", "debo", "disponible",
        "cuota", "que es", "significa", "movimiento",
    )):
        return False
    return any(s in q for s in (
        "dame la de", "dame el de", "dame la ", "dame el ",
        "la del ", "el del ", "la de ", "el de ",
    ))


def prior_personal_question(session: Any | None) -> str | None:
    """Última pregunta personal sustantiva, ignorando refs de card y reescrituras de un solo campo."""
    if session is None:
        return None
    hist = list(getattr(session, "history", None) or [])
    for item in reversed(hist):
        if not isinstance(item, dict):
            continue
        raw = str(item.get("question") or "").strip()
        n = _norm(raw)
        if not n or re.match(r"^(tarjeta|prestamo|cuenta|deposito)_\d+", n):
            continue
        if "saldo disponible de mi" in n:
            continue
        if any(s in n for s in ("debo", "disponible", "fecha", "tasa", "cuota", "saldo", "adeud", "cancel")):
            return raw
    for pt in reversed(list(getattr(session, "pending_tasks", None) or [])):
        if isinstance(pt, dict) and pt.get("original_question"):
            return str(pt["original_question"])
    return None


def _match_portfolio_by_text(question: str, snapshot: Any) -> list[Any]:
    """Resuelve productos del snapshot por alias/dígitos/ref (p. ej. tarjeta joven)."""
    active = _active_products(snapshot)
    if not active:
        return []
    # Catálogo Potenciación: discrimina crédito/débito Joven sin inventar tenencia
    try:
        from genesis_cognitive.context.product_catalog_aliases import (
            resolve_portfolio_by_catalog,
        )
        catalog_hits, reason = resolve_portfolio_by_catalog(question, active)
        if reason == "unique" and len(catalog_hits) == 1:
            return catalog_hits
        if reason in ("ambiguous", "ambiguous_family") and catalog_hits:
            return catalog_hits
    except Exception:
        pass
    try:
        from genesis_cognitive.router.deposit_guardrail import _find_text_candidates
        return list(_find_text_candidates(_norm(question), active) or [])
    except Exception:
        q = _norm(question)
        hits = []
        for p in active:
            alias = _norm(str(getattr(p, "alias", "") or ""))
            if alias and len(alias) >= 4 and alias in q:
                hits.append(p)
        return hits


def _plan_field_for_product(
    *,
    products: list[Any],
    field: str,
    n: int,
    filters: dict[str, Any] | None = None,
) -> tuple[PlanTask, int]:
    """Una tarea personal sobre 0/1/N productos del mismo o distinto tipo."""
    filters = dict(filters or {})
    if not products:
        # Ausencia: objeto genérico loan para tasa; account para saldo
        obj = "loan" if field == "rate" else ("term_deposit" if field == "maturity" else "account")
        return PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object=obj, fields=[field], status="ready",
            filters={**filters, "portfolio_gap": True},
        ), n + 1
    if len(products) == 1:
        p = products[0]
        obj = _TYPE_TO_OBJECT.get(str(p.product_type), "account")
        return PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object=obj, fields=[field], entity_ref=p.product_id,
            status="ready", filters=filters,
        ), n + 1
    types = {str(p.product_type) for p in products}
    if len(types) == 1:
        obj = _TYPE_TO_OBJECT.get(next(iter(types)), "account")
    else:
        obj = "product"
    ids = [str(p.product_id) for p in products]
    return PlanTask(
        id=_next_id(n), domain="personal", action="read_field",
        object=obj, fields=[field],
        status="needs_clarification",
        unresolved_slots=["entity_ref"],
        filters={
            **filters,
            "candidate_ids": ids,
            "clarify_field": field,
        },
    ), n + 1


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
    # Si la pregunta es de tarjeta, no crear tarea de cuenta espuria.
    if any(s in q for s in ("movimientos", "ultimos movimientos", "últimos movimientos", "transacciones")):
        cardish = any(s in q for s in ("tarjeta", "visa", "mastercard", "credito", "crédito"))
        # No crear cuenta aquí si también pide balance/disponible: lo arma el bloque multi-campo
        # (evita clarificación + available duplicado). Solo movements unsupported.
        mov_obj = "credit_card" if cardish else "account"
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object=mov_obj, fields=["movements"],
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

    # ── Conocimiento P0: Joven / reclamaciones / fallecidos (sin LLM) ──
    if any(s in q for s in ("fallec", "de cujus")) and any(
        s in q for s in ("familiar", "producto", "hacer", "proced", "retiro", "cliente")
    ):
        tasks.append(PlanTask(
            id=_next_id(1), domain="process", action="process", object="process",
            fields=["procedure"], status="ready",
            filters={"query": raw},
        ))
        return TurnPlan(tasks=tasks, transition="none", source="kb_fallecidos")
    if "reclam" in q and not any(s in q for s in ("debo", "saldo", "disponible", "cuota")):
        tasks.append(PlanTask(
            id=_next_id(1), domain="process", action="process", object="process",
            fields=["procedure"], status="ready",
            filters={"query": raw},
        ))
        return TurnPlan(tasks=tasks, transition="none", source="kb_reclamacion")
    if "joven" in q and any(s in q for s in ("caracter", "dirigida", "que es", "qué es", "informacion", "información")):
        obj = "visa_joven_debito" if ("debito" in q and "credito" not in q) else "visa_joven"
        tasks.append(PlanTask(
            id=_next_id(1), domain="catalog", action="define", object=obj,
            fields=["features"], status="ready",
            filters={"query": raw},
        ))
        return TurnPlan(tasks=tasks, transition="none", source="kb_joven")

    # ── Conteo de productos propios («cuántos préstamos tengo») ──
    if re.search(r"\bcuant[oa]s\b", q) and not any(s in q for s in ("dias", "meses", "puntos", "anos", "años")):
        count_obj = None
        if any(s in q for s in ("prestamo", "préstamo")):
            count_obj = "loan"
        elif "tarjeta" in q:
            count_obj = "credit_card"
        elif any(s in q for s in ("certificado", "dap", "deposito a plazo", "depósito a plazo")):
            count_obj = "term_deposit"
        elif "cuenta" in q:
            count_obj = "account"
        elif "producto" in q:
            count_obj = "portfolio"
        if count_obj:
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="count",
                object=count_obj, fields=["count"], status="ready",
            ))
            return TurnPlan(tasks=tasks, transition="none", source=source)

    # Mismo pedido, otro producto: «dame la de multicrédito»
    if is_product_pointer(raw) and session is not None and snapshot is not None:
        prev = prior_personal_question(session)
        mentioned = _match_portfolio_by_text(raw, snapshot)
        if prev and len(mentioned) == 1:
            prior = interpret_turn_plan(prev, None, snapshot=snapshot)
            fields: list[str] = []
            for t in prior.tasks:
                if t.domain != "personal":
                    continue
                for fld in t.fields or []:
                    if fld not in fields and fld not in ("list", "presence", "features", "count"):
                        fields.append(fld)
            if fields:
                p = mentioned[0]
                obj = _TYPE_TO_OBJECT.get(str(p.product_type), "product")
                tasks.append(PlanTask(
                    id=_next_id(1), domain="personal", action="read_field",
                    object=obj, fields=fields, entity_ref=p.product_id, status="ready",
                ))
                return TurnPlan(tasks=tasks, transition="selection", source="replay_prior_fields")

    # ── Existencia personal tras catálogo (MIX07) ──
    existence = any(
        s in q for s in (
            "tengo yo ese", "tengo ese producto", "yo tengo ese",
            "lo tengo", "tengo yo", "poseo ese",
        )
    )
    catalog_refs = detect_catalog_refs(raw)
    compare_ask = any(s in q for s in ("compara", "comparame", "compárame", "vs ")) or (
        "diferencia" in q and "entre" in q
    )
    # Comparación de portafolio personal (mis certificados/tarjetas) ≠ catálogo KB
    personal_compare = compare_ask and any(
        s in q
        for s in (
            "mis certificados", "certificados financieros", "mis dap",
            "mis tarjetas", "mis prestamos", "mis préstamos", "mis cuentas",
            "mis depositos", "mis depósitos",
        )
    )
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

    # ── Comparación de catálogo (CC02/CC03) — no aplica a «compárame mis certificados» ──
    if (compare_ask or add_to_compare or remove_from_compare) and not personal_compare:
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
        "como funciona la cancelacion", "cómo funciona la cancelación",
        "funciona la cancelacion", "funciona la cancelación",
        "cancelacion de prestamo", "cancelación de préstamo",
        "cancelacion de prestamos", "cancelación de préstamos",
    )):
        if "igual" in q or "compara" in q or ("tarjeta" in q and "prestamo" in q):
            tasks.append(PlanTask(
                id=_next_id(n), domain="process", action="compare",
                object="cancellation", fields=["process"], cardinality="compare",
                filters={"entities": ["credit_card", "loan"], "query": raw},
                status="ready",
            ))
            n += 1
        elif "mi " not in q or "monto" not in q:
            # Distinguir préstamo personal vs crédito diferido / Multicrédito
            cancel_obj = "loan_cancellation" if any(
                s in q for s in ("prestamo", "préstamo", "prestamos", "préstamos")
            ) and "multicredit" not in q and "credito diferido" not in q else "cancellation"
            tasks.append(PlanTask(
                id=_next_id(n), domain="process", action="process",
                object=cancel_obj, fields=["process"], status="ready",
                filters={"query": raw, "product_family": "loan" if cancel_obj == "loan_cancellation" else "deferred_credit"},
            ))
            n += 1

    # Cargos / comisiones de tarjeta (conocimiento, no historial personal)
    if any(s in q for s in ("cargo", "cargos", "comision", "comisión")) and "tarjeta" in q:
        if not any(s in q for s in ("me cobraron", "me cobro", "recientemente", "historial")):
            if not any(t.domain == "catalog" and "cargo" in (t.object or "") for t in tasks):
                tasks.append(PlanTask(
                    id=_next_id(n), domain="catalog", action="define",
                    object="cargo_tarjeta", fields=["info"], status="ready",
                    filters={"query": raw or "qué cargos puede tener una tarjeta"},
                ))
                n += 1

    # ── Definición de saldo disponible (conocimiento) ──
    # Acepta artículo opcional: «qué significa el saldo disponible…»
    wants_available_def = bool(
        re.search(
            r"(que|qué)\s+(significa|es)\s+(el\s+)?saldo\s+disponible",
            q,
        )
        or re.search(r"definici[oó]n\s+(del?\s+)?saldo\s+disponible", q)
    )
    if wants_available_def:
        tasks.append(PlanTask(
            id=_next_id(n), domain="institutional", action="define",
            object="glossary", fields=["available_balance"], status="ready",
        ))
        n += 1

    # ── Personal: liquidez / saldo ──
    wants_available = (
        (
            "disponible" in q
            and "significa" not in q
            and "que es" not in q
            and "qué es" not in q
            and not wants_available_def
        )
        or any(s in q for s in (
            "con cuanto puedo contar", "con cuánto puedo contar",
            "cuanto puedo contar", "cuánto puedo contar",
            "puedo contar", "liquidez",
        ))
    )
    wants_current = any(s in q for s in ("saldo actual", "balance actual", "saldo contable"))
    wants_balance = wants_current or (
        "saldo" in q and not wants_available and "significa" not in q
    )
    mentions_card = any(s in q for s in ("tarjeta", "visa", "mastercard", "tc "))
    mentions_account = any(s in q for s in ("cuenta", "ahorros", "ahorro", "corriente", "nomina", "nómina"))
    mentions_loan = any(s in q for s in ("prestamo", "préstamo")) or (
        "cuota" in q and not mentions_card
    )
    mentions_dap = any(s in q for s in ("certificado", "dap", "deposito a plazo", "depósito a plazo", "mis certificados"))
    # Foco de sesión no debe arrastrar TC a una pregunta explícita de préstamo/cuenta
    loan_exclusive = mentions_loan and not mentions_card
    account_exclusive = mentions_account and not mentions_card and not mentions_loan
    card_focus_ok = focus_kind == "CARD" and not loan_exclusive and not account_exclusive
    card_trigger = bool(mentions_card or card_focus_ok or False)

    # Typos frecuentes (X01 / V3-19)
    typo_debt = bool(re.search(r"\b(debo|deuda|adeud|k debo|e k debo)\b", q)) or "debo" in q.replace(" ", "")
    typo_pay = any(s in q for s in (
        "cuando me toca pagar", "cuando pago", "cuándo pago", "fecha de pago",
        "tocar pagar", "cuando debo pagar", "debo pagar",
    ))

    # ── Definición de tasa + tasa personal (V3-20) ──
    wants_rate_definition = "tasa" in q and any(
        s in q for s in ("significa", "que significa", "qué significa", "definicion", "definición")
    ) and not re.search(r"\bmi\s+tasa\b", q)
    # «qué es la tasa» (glosario) vs «cuál es mi tasa» (personal)
    if "tasa" in q and any(s in q for s in ("que es la tasa", "qué es la tasa", "que es tasa", "qué es tasa")):
        wants_rate_definition = True
    wants_my_rate = "tasa" in q and (
        re.search(r"\bmi\s+tasa\b", q)
        or any(s in q for s in (
            "mi tasa", "tasa de mi", "tasa de interes", "tasa de interés",
            "tasa anual", "interes de mi", "interés de mi",
        ))
        or (
            any(s in q for s in ("prestamo", "préstamo", "mi prestamo", "mi préstamo"))
            and "tasa" in q
        )
    ) and "significa" not in q

    if wants_rate_definition:
        tasks.append(PlanTask(
            id=_next_id(n), domain="institutional", action="define",
            object="glossary", fields=["interest_rate"], status="ready",
        ))
        n += 1
        if any(s in q for s in ("mi prestamo", "mi préstamo", "prestamo", "préstamo", "mi tasa")):
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
    elif wants_my_rate:
        # Tasa personal según portafolio: préstamos, certificados y tarjetas con tasa
        mentioned = _match_portfolio_by_text(raw, snapshot)
        if mentioned:
            rate_pool = [p for p in mentioned if _product_bears_rate(p)]
        else:
            active = _active_products(snapshot)
            if any(s in q for s in ("prestamo", "préstamo")):
                rate_pool = [p for p in active if p.product_type == "LOAN"]
            elif any(s in q for s in ("certificado", "dap", "deposito a plazo", "depósito a plazo", "cdt")):
                rate_pool = [p for p in active if p.product_type == "TERM_DEPOSIT"]
            elif any(s in q for s in ("tarjeta", "visa", "mastercard")):
                rate_pool = [p for p in active if p.product_type == "CREDIT_CARD" and _product_bears_rate(p)]
            else:
                rate_pool = [p for p in active if _product_bears_rate(p)]
        task, n = _plan_field_for_product(products=rate_pool, field="rate", n=n)
        tasks.append(task)

    # Alias / dígitos del portafolio + campo pedido (p. ej. «saldo de mi tarjeta joven»)
    # Solo si aún no hay tarea personal con entity o aclaración de tasa ya creada
    # Ni multi-campo de tarjeta ya planificado (P01/P02)
    matched_products = _match_portfolio_by_text(raw, snapshot)
    has_multicard = any(
        t.object == "credit_card" and t.action == "read_field"
        and len([f for f in (t.fields or []) if f != "movements"]) >= 2
        for t in tasks
    )
    if (
        matched_products
        and not wants_my_rate
        and not has_multicard
        and not any(t.domain == "personal" and (t.entity_ref or t.status == "needs_clarification") for t in tasks)
    ):
        fields_alias: list[str] = []
        # No convertir glosario («qué significa el saldo disponible…») en lectura personal
        if not wants_available_def and "significa" not in q:
            if "tasa" in q or "interes" in q or "interés" in q:
                fields_alias.append("rate")
            if any(s in q for s in (
                "inverti", "invertí", "invertido", "cuanto inverti", "cuánto invertí",
                "cuanto invertí", "capital invert", "monto invert",
            )):
                fields_alias.append("principal")
            if any(s in q for s in (
                "ha generado", "generado", "intereses acumul", "interes acumul",
                "interés acumul", "rendimiento", "cuanto ha generado", "cuánto ha generado",
            )):
                fields_alias.append("interest_amount")
            if wants_available or "disponible" in q:
                fields_alias.append("available")
            elif wants_balance or "saldo" in q or "balance" in q:
                if any(str(getattr(p, "product_type", "")) == "CREDIT_CARD" for p in matched_products):
                    fields_alias.append("balance")
                elif any(str(getattr(p, "product_type", "")) == "TERM_DEPOSIT" for p in matched_products):
                    fields_alias.append("principal")
                elif "principal" not in fields_alias:
                    fields_alias.append("balance" if wants_current else "available")
            if any(s in q for s in ("vence", "vencimiento", "madurez")):
                # «vence la próxima cuota del préstamo» → due_date, no maturity de DAP
                if "cuota" in q or mentions_loan:
                    pass
                else:
                    fields_alias.append("maturity")
            if any(s in q for s in ("pago minimo", "mínimo", "minimo")):
                fields_alias.append("min_payment")
        if fields_alias:
            # Una sola tarea multi-campo (evita clarificación duplicada por campo)
            types = {str(getattr(p, "product_type", "")) for p in matched_products}
            force_all_alias = (
                personal_compare
                or any(s in q for s in (
                    "mis certificados", "certificados financieros",
                    "todos los certificados", "listame", "listar",
                ))
                or any(s in q for s in (
                    "primero en vencer", "vence primero", "cual vence", "cuál vence",
                ))
            )
            if len(types) == 1 and "TERM_DEPOSIT" in types:
                pool = list(matched_products)
                # Filtrar pool por campos que el producto puede responder
                if "rate" in fields_alias:
                    rate_ok = [p for p in pool if _product_bears_rate(p)]
                    if rate_ok:
                        pool = rate_ok
                order = ["principal", "rate", "interest_amount", "maturity", "balance", "available"]
                ordered = [f for f in order if f in fields_alias] + [
                    f for f in fields_alias if f not in order
                ]
                excl_td: list[str] = []
                if any(s in q for s in (
                    "no el balance", "sin balance", "no necesito el balance",
                    "no el capital", "sin capital",
                )):
                    excl_td = ["balance", "capital", "principal"]
                    ordered = [f for f in ordered if f not in ("principal", "balance", "capital")]
                if force_all_alias or len(pool) == 1:
                    tasks.append(PlanTask(
                        id=_next_id(n), domain="personal", action="read_field",
                        object="term_deposit", fields=ordered or ["rate", "maturity"],
                        cardinality="all" if force_all_alias or len(pool) > 1 else "single",
                        exclusions=excl_td,
                        entity_ref=pool[0].product_id if len(pool) == 1 and not force_all_alias else None,
                        status="ready",
                    ))
                    n += 1
                    if any(s in q for s in (
                        "primero en vencer", "vence primero", "cual vence", "cuál vence",
                    )) or (personal_compare and "vence" in q):
                        tasks.append(PlanTask(
                            id=_next_id(n), domain="personal", action="compare",
                            object="term_deposit", fields=["maturity"], cardinality="all",
                            filters={"operator": "earliest"}, exclusions=excl_td,
                            status="ready",
                        ))
                        n += 1
                else:
                    tasks.append(PlanTask(
                        id=_next_id(n), domain="personal", action="read_field",
                        object="term_deposit", fields=ordered,
                        status="needs_clarification",
                        unresolved_slots=["entity_ref"],
                        filters={"candidate_ids": [str(p.product_id) for p in pool]},
                    ))
                    n += 1
            else:
                # Preferir listado/comparación personal sobre clarificación 1-a-1
                force_all = (
                    personal_compare
                    or any(s in q for s in (
                        "mis certificados", "certificados financieros",
                        "todos los certificados", "listame", "listar",
                    ))
                    or any(s in q for s in (
                        "primero en vencer", "vence primero", "cual vence", "cuál vence",
                    ))
                )
                if force_all and matched_products:
                    types = {str(getattr(p, "product_type", "")) for p in matched_products}
                    if len(types) == 1:
                        obj = _TYPE_TO_OBJECT.get(next(iter(types)), "account")
                        order = ["principal", "rate", "interest_amount", "maturity", "balance", "available"]
                        ordered = [f for f in order if f in fields_alias] + [
                            f for f in fields_alias if f not in order
                        ]
                        excl_early: list[str] = []
                        if any(s in q for s in (
                            "no el balance", "sin balance", "no necesito el balance",
                            "no el capital", "sin capital",
                        )):
                            excl_early = ["balance", "capital", "principal"]
                            ordered = [f for f in ordered if f not in ("principal", "balance", "capital")]
                        tasks.append(PlanTask(
                            id=_next_id(n), domain="personal", action="read_field",
                            object=obj, fields=ordered or fields_alias, cardinality="all",
                            exclusions=excl_early, status="ready",
                        ))
                        n += 1
                        if any(s in q for s in (
                            "primero en vencer", "vence primero", "cual vence", "cuál vence",
                        )) or (personal_compare and "vence" in q):
                            tasks.append(PlanTask(
                                id=_next_id(n), domain="personal", action="compare",
                                object=obj, fields=["maturity"], cardinality="all",
                                filters={"operator": "earliest"}, exclusions=excl_early,
                                status="ready",
                            ))
                            n += 1
                    else:
                        for fld in fields_alias:
                            pool = matched_products
                            if fld == "rate":
                                pool = [p for p in matched_products if _product_bears_rate(p)]
                            if fld == "maturity":
                                pool = [p for p in matched_products if _product_bears_maturity(p)]
                            task, n = _plan_field_for_product(products=pool, field=fld, n=n)
                            tasks.append(task)
                else:
                    for fld in fields_alias:
                        pool = matched_products
                        if fld == "rate":
                            pool = [p for p in matched_products if _product_bears_rate(p)]
                        if fld == "maturity":
                            pool = [p for p in matched_products if _product_bears_maturity(p)]
                        task, n = _plan_field_for_product(products=pool, field=fld, n=n)
                        tasks.append(task)

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

    # Corrección explícita de producto — cambia solo la consulta personal referida
    if any(s in q for s in ("no la", "no, la", "no, me", "me referia", "me refería", "la corriente", "la de ahorros", "la otra")):
        transition = "correction"
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
        field = "balance" if ("saldo actual" in q or "saldo contable" in q or ("actual" in q and "disponible" not in q)) else (
            "available" if wants_available else "balance"
        )
        entity = None
        want_type = filters_corr.get("account_subtype")
        status_corr = "ready"
        unresolved_corr: list[str] = []
        if snapshot is not None and want_type:
            matches = [
                p for p in snapshot.products
                if p.product_type == want_type and str(p.status).lower() == "active"
            ]
            if len(matches) == 1:
                entity = matches[0].product_id
            elif len(matches) > 1:
                status_corr = "needs_clarification"
                unresolved_corr = ["entity_ref"]
        # Conservar tareas institucionales del mismo mensaje (misión/visión/definición)
        inst_keep = [t for t in tasks if t.domain == "institutional"]
        tasks = [
            PlanTask(
                id=_next_id(1), domain="personal", action="read_field",
                object=obj, fields=[field],
                filters=filters_corr, entity_ref=entity, status=status_corr,
                unresolved_slots=unresolved_corr,
            ),
            *inst_keep,
        ]
        # Si el mensaje pide misión/visión y aún no está
        n_inst = len(tasks) + 1
        if "mision" in q and not any("mision" in (t.fields or []) for t in tasks):
            tasks.append(PlanTask(
                id=_next_id(n_inst), domain="institutional", action="define",
                object="bank", fields=["mision"], status="ready",
            ))
            n_inst += 1
        if "vision" in q and not any("vision" in (t.fields or []) for t in tasks):
            tasks.append(PlanTask(
                id=_next_id(n_inst), domain="institutional", action="define",
                object="bank", fields=["vision"], status="ready",
            ))
        # Re-id
        for i, t in enumerate(tasks, start=1):
            t.id = f"t{i}"
        plan = TurnPlan(tasks=tasks, transition="correction", source=source)
        errors = validate_turn_plan(plan)
        if errors:
            from genesis_cognitive.brain.turn_plan import InvalidTurnPlanError
            raise InvalidTurnPlanError(errors)
        return plan

    # Multi-campo tarjeta (P01/P02): deuda + disponible + fecha + mínimo
    card_fields: list[str] = []
    if card_trigger or (typo_debt and "tarjeta" in q):
        if (
            typo_debt
            or wants_current
            or any(s in q for s in (
                "debo", "deuda", "adeudado", "cuanto debo", "cuánto debo",
                "saldo actual", "saldo adeud", "balance actual",
            ))
            or ("saldo" in q and "disponible" in q)  # pide ambos: incluir adeudado
        ):
            if "balance" not in card_fields:
                card_fields.append("balance")
        # Disponible de tarjeta: evitar atribuir «disponible de mi cuenta» a la TC (P08)
        avail_for_card = False
        if wants_available or "disponible" in q or "cupo" in q or "limite disponible" in q or "límite disponible" in q:
            if "tarjeta" in q:
                # ¿«disponible» aparece ligado a cuenta/corriente/ahorros?
                m_disp = re.search(r".{0,40}disponible.{0,40}", q)
                chunk = m_disp.group(0) if m_disp else q
                if not any(s in chunk for s in ("cuenta", "ahorros", "ahorro", "corriente")):
                    avail_for_card = True
                elif "tarjeta" in chunk and "disponible" in chunk:
                    avail_for_card = True
            elif not mentions_account:
                avail_for_card = True
        if avail_for_card:
            card_fields.append("available")
        if typo_pay or any(s in q for s in (
            "fecha de pago", "fecha limite", "fecha límite", "limite de pago", "límite de pago",
            "fecha limite de pago", "fecha límite de pago",
            "cuando pago", "cuándo pago", "tocar pagar",
            "cuando me toca", "cuando debo pagar", "debo pagar", "cuando pagar",
            "cuando es mi fecha", "cuándo es mi fecha",
        )):
            if "pago minimo" not in q and "minimo" not in q and "mínimo" not in q:
                card_fields.append("due_date")
        if any(s in q for s in ("pago minimo", "mínimo", "minimo")) and "significa" not in q:
            card_fields.append("min_payment")
        if any(s in q for s in ("movimientos", "transacciones", "ultimos movimientos", "últimos movimientos")):
            # Se maneja como tarea unsupported aparte; no mezclar en fields grounded
            pass

    # Dígitos explícitos — saltar si el mensaje es marco de secreto (ya manejado arriba)
    digit_hints = re.findall(r"\d{4,}", raw)
    digit_entity = None
    if snapshot is not None and digit_hints:
        # Preferir last_four / card_mask (••••8891) antes que product_id
        for d in digit_hints:
            tail = d[-4:]
            for p in getattr(snapshot, "products", ()) or ():
                last4 = str(getattr(p, "last_four", "") or "")
                mask = "".join(ch for ch in str(getattr(p, "card_mask", "") or "") if ch.isdigit())
                if last4 == tail or (mask and mask.endswith(tail)):
                    digit_entity = str(getattr(p, "product_id", "") or "")
                    break
            if digit_entity:
                break
        if not digit_entity:
            for p in getattr(snapshot, "products", ()) or ():
                pid = str(getattr(p, "product_id", "") or "")
                for d in digit_hints:
                    if pid.endswith(d) or pid.endswith(d[-4:]):
                        digit_entity = pid
                        break
                if digit_entity:
                    break

    if len(card_fields) >= 1 and (card_trigger or (typo_debt and "tarjeta" in q)):
        status = "ready"
        unresolved: list[str] = []
        entity = digit_entity or (focus_id if card_focus_ok else None)
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
        # Fusionar con tarea credit_card previa (evitar duplicados available/balance)
        existing_card = next(
            (
                t for t in tasks
                if t.object == "credit_card"
                and t.action == "read_field"
                and "movements" not in (t.fields or [])
            ),
            None,
        )
        if existing_card is not None and "movements" not in (existing_card.fields or []):
            merged = list(existing_card.fields or [])
            for f in card_fields:
                if f not in merged:
                    merged.append(f)
            # Orden preferente cobertura P02
            order = ["balance", "min_payment", "available", "due_date"]
            existing_card.fields = [f for f in order if f in merged] + [f for f in merged if f not in order]
            if entity and not existing_card.entity_ref:
                existing_card.entity_ref = entity
            if status == "needs_clarification":
                existing_card.status = status
                existing_card.unresolved_slots = unresolved
                existing_card.filters = {
                    **dict(existing_card.filters or {}),
                    "candidate_ids": [p.product_id for p in cards],
                }
        else:
            order = ["balance", "min_payment", "available", "due_date"]
            ordered = [f for f in order if f in card_fields] + [f for f in card_fields if f not in order]
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="credit_card", fields=ordered or ["available"],
                cardinality="single", entity_ref=entity,
                status=status, unresolved_slots=unresolved,
                filters={"candidate_ids": [p.product_id for p in cards]} if status == "needs_clarification" and cards else {},
            ))
            n += 1
        # Si hay movimientos pedidos junto a tarjeta, asegurar tarea unsupported de tarjeta
        if any(s in q for s in ("movimientos", "transacciones")):
            if not any(t.fields == ["movements"] for t in tasks):
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="credit_card", fields=["movements"], status="unsupported",
                ))
                n += 1
            # Eliminar tarea account+available creada solo por co-ocurrencia con movimientos
            tasks = [
                t for t in tasks
                if not (
                    t.object == "account"
                    and t.fields == ["available"]
                    and mentions_card
                    and not mentions_account
                )
            ]
        # Colapsar tarjetas duplicadas: conservar la de más campos (excl. movements)
        card_keep: list = []
        other_tasks: list = []
        best_card = None
        for t in tasks:
            if t.object == "credit_card" and t.action == "read_field" and "movements" not in (t.fields or []):
                if best_card is None or len(t.fields or []) >= len(best_card.fields or []):
                    best_card = t
            else:
                other_tasks.append(t)
        tasks = other_tasks + ([best_card] if best_card is not None else [])

    # Multi-campo préstamo (P03/P04/P13): saldo + cuota + fecha / tasa + cancelación
    loan_hint_personal = any(s in q for s in ("prestamo personal", "préstamo personal", "personal"))
    loan_hint_mortgage = any(s in q for s in ("hipotecario", "hipoteca", "vivienda"))
    wants_loan_payoff = any(s in q for s in (
        "cancelarlo", "para cancelar", "saldo de cancelacion",
        "saldo de cancelación", "necesito para cancelar", "faltaria para cancelar",
        "faltaría para cancelar", "cuanto necesitaria", "cuánto necesitaría",
        "cancelar el mio", "cancelar el mío", "pagar para cancelar",
        "tendria que pagar", "tendría que pagar", "cuanto tendria", "cuánto tendría",
    )) or (
        "cancelar" in q
        and any(s in q for s in ("cuanto", "cuánto", "monto", "el mio", "el mío", "mi prestamo", "mi préstamo"))
        and not any(s in q for s in ("como funciona", "cómo funciona", "proceso de", "que es el proceso"))
    )
    wants_loan_installment = (
        "cuota" in q
        and any(s in q for s in ("cuanto", "cuánto", "proxima", "próxima", "monto", "de mi"))
        and "cuando" not in q.split("cuota")[0][-20:]  # «cuándo…cuota» → fecha
        and not any(s in q for s in ("cuando vence", "cuándo vence", "vence la proxima cuota", "vence la próxima cuota"))
    ) or any(s in q for s in ("cuanto es mi cuota", "cuánto es mi cuota", "cuanto es la cuota", "cuánto es la cuota"))
    wants_loan_due = any(s in q for s in (
        "cuando me toca", "cuándo me toca", "cuando pagar", "cuándo pagar",
        "fecha de pago", "cuando debo pagar", "cuándo debo pagar", "tocar pagarla",
        "pagarla", "cuando vence", "cuándo vence", "vence la proxima cuota", "vence la próxima cuota",
    )) and mentions_loan
    # Si solo pregunta cuándo vence la cuota (no el monto), no pedir installment_amount
    import re as _re_wants
    _cuota_win = _re_wants.search(r".{0,50}cuota.{0,50}", q)
    _cuota_ctx = _cuota_win.group(0) if _cuota_win else ""
    if _cuota_ctx and any(s in _cuota_ctx for s in ("cuando", "cuándo", "vence")) and not any(
        s in _cuota_ctx for s in ("cuanto", "cuánto", "monto")
    ):
        wants_loan_installment = False
        wants_loan_due = True
    wants_loan_principal = any(s in q for s in (
        "cuanto debo", "cuánto debo", "saldo", "capital", "cuanto me falta", "cuánto me falta",
        "me falta del", "adeud",
    )) and mentions_loan and not mentions_card

    loan_fields: list[str] = []
    if mentions_loan and not mentions_card:
        if wants_loan_principal:
            loan_fields.append("principal")
        if wants_loan_payoff:
            loan_fields.append("payoff")
        if wants_loan_installment or ("cuota" in q and ("cuanto" in q or "cuánto" in q or "proxima" in q or "próxima" in q)):
            if "installment_amount" not in loan_fields:
                loan_fields.append("installment_amount")
        if wants_loan_due or ("cuando" in q or "cuándo" in q) and "cuota" in q and mentions_loan:
            if "due_date" not in loan_fields:
                loan_fields.append("due_date")
        if "tasa" in q and "significa" not in q:
            loan_fields.append("rate")

    # P13: atributos distintos por tipo de préstamo en el mismo mensaje
    split_personal_mortgage = (
        loan_hint_personal and loan_hint_mortgage
        and ("prestamo" in q or "préstamo" in q)
    )
    split_done = False
    if split_personal_mortgage and snapshot is not None:
        loans_all = [
            p for p in getattr(snapshot, "products", ()) or ()
            if getattr(p, "product_type", "") == "LOAN"
            and str(getattr(p, "status", "")).lower() == "active"
        ]
        pers = [
            p for p in loans_all
            if "personal" in _norm(str(getattr(p, "alias", "") or ""))
            or "personal" in _norm(str(getattr(p, "product_id", "") or ""))
        ]
        # Match por descripción vía loans snapshot
        if not pers and getattr(snapshot, "loans", None):
            pers_ids = {
                ln.product_id for ln in snapshot.loans
                if "personal" in _norm(ln.loan_type or "")
            }
            pers = [p for p in loans_all if p.product_id in pers_ids]
        mort = [
            p for p in loans_all
            if "hipotec" in _norm(str(getattr(p, "alias", "") or ""))
        ]
        if not mort and getattr(snapshot, "loans", None):
            mort_ids = {
                ln.product_id for ln in snapshot.loans
                if "hipotec" in _norm(ln.loan_type or "")
            }
            mort = [p for p in loans_all if p.product_id in mort_ids]
        pers_fields: list[str] = []
        # Campos del personal: solo lo pedido en el tramo personal
        if any(s in q for s in ("saldo", "debo", "capital", "pendiente")):
            # Evitar atribuir «saldo» del hipotecario al personal cuando el saldo
            # va explícitamente ligado al personal
            pers_fields.append("principal")
        if "cuota" in q and (
            "personal" in q.split("hipotec")[0]
            or "personal" in q
        ):
            pers_fields.append("installment_amount")
        if not pers_fields:
            pers_fields = ["principal", "installment_amount"]
        # Hipotecario: solo tasa si así se pidió
        mort_fields: list[str] = []
        if "tasa" in q:
            mort_fields.append("rate")
        if not mort_fields:
            mort_fields = ["rate"]
        # Limpiar tareas préstamo previas genéricas antes de fijar por tipo
        tasks = [t for t in tasks if t.object != "loan"]
        if pers:
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="loan", fields=pers_fields,
                entity_ref=pers[0].product_id, status="ready",
                filters={"loan_role": "personal"},
            ))
            n += 1
        if mort:
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="loan", fields=mort_fields,
                entity_ref=mort[0].product_id, status="ready",
                filters={"loan_role": "mortgage"},
            ))
            n += 1
        loan_fields = []  # ya resuelto por tipo
        # Marca para que el bloque cross-product no ensanche campos
        split_done = True

    if loan_fields and not split_done:
        existing_loan = next((t for t in tasks if t.object == "loan"), None)
        if existing_loan is not None:
            merged = list(existing_loan.fields or [])
            for f in loan_fields:
                if f not in merged:
                    merged.append(f)
            existing_loan.fields = merged
            # Preferir principal/payoff/cuota sobre «available» genérico mal atribuido
            existing_loan.fields = [
                f for f in existing_loan.fields
                if f not in ("available",) or "disponible" in q and "prestamo" in q and "cuenta" not in q
            ] or merged
        else:
            loans = []
            if snapshot is not None:
                loans = [
                    p for p in getattr(snapshot, "products", ()) or ()
                    if getattr(p, "product_type", "") == "LOAN"
                    and str(getattr(p, "status", "")).lower() == "active"
                ]
                if loan_hint_personal and not loan_hint_mortgage:
                    filtered = []
                    for p in loans:
                        alias = _norm(str(getattr(p, "alias", "") or ""))
                        if "personal" in alias:
                            filtered.append(p)
                    if not filtered and getattr(snapshot, "loans", None):
                        ids = {
                            ln.product_id for ln in snapshot.loans
                            if "personal" in _norm(ln.loan_type or "")
                        }
                        filtered = [p for p in loans if p.product_id in ids]
                    if filtered:
                        loans = filtered
                elif loan_hint_mortgage and not loan_hint_personal:
                    filtered = []
                    for p in loans:
                        alias = _norm(str(getattr(p, "alias", "") or ""))
                        if "hipotec" in alias:
                            filtered.append(p)
                    if not filtered and getattr(snapshot, "loans", None):
                        ids = {
                            ln.product_id for ln in snapshot.loans
                            if "hipotec" in _norm(ln.loan_type or "")
                        }
                        filtered = [p for p in loans if p.product_id in ids]
                    if filtered:
                        loans = filtered
            entity = digit_entity if digit_entity and any(
                p.product_id == digit_entity for p in loans
            ) else (focus_id if focus_kind == "LOAN" else None)
            status = "ready"
            unresolved: list[str] = []
            if entity is None and len(loans) == 1:
                entity = loans[0].product_id
            elif entity is None and len(loans) > 1:
                status = "needs_clarification"
                unresolved = ["entity_ref"]
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="loan", fields=loan_fields, cardinality="single",
                entity_ref=entity, status=status, unresolved_slots=unresolved,
                filters={"candidate_ids": [p.product_id for p in loans]} if len(loans) > 1 else {},
            ))
            n += 1

    # Multi-producto en una pregunta (P07/P08/P11/P14)
    mentions_savings = any(s in q for s in ("ahorros", "ahorro"))
    mentions_checking = any(s in q for s in ("corriente",))
    cross_product = (
        (mentions_savings or mentions_checking or ("cuentas" in q))
        and (mentions_card or mentions_loan)
    ) or (mentions_card and mentions_loan and mentions_account)
    if cross_product:
        has_card_task = any(t.object == "credit_card" for t in tasks)
        has_loan_task = any(t.object == "loan" for t in tasks)
        has_acct_task = any(t.object == "account" for t in tasks)
        if (mentions_savings or mentions_checking or ("cuentas" in q and "tengo" in q)) and not has_acct_task:
            acct_types = []
            if mentions_savings:
                acct_types.append("SAVINGS")
            if mentions_checking:
                acct_types.append("CHECKING")
            if not acct_types and "cuentas" in q:
                acct_types = ["SAVINGS", "CHECKING", "PAYROLL"]
            accts = []
            if snapshot is not None:
                accts = [
                    p for p in getattr(snapshot, "products", ()) or ()
                    if getattr(p, "product_type", "") in (acct_types or ("SAVINGS", "CHECKING", "PAYROLL"))
                    and str(getattr(p, "status", "")).lower() == "active"
                ]
            acct_fields = ["available"] if "disponible" in q else ["balance"]
            if len(accts) == 1:
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="account", fields=acct_fields,
                    entity_ref=accts[0].product_id, status="ready",
                ))
                n += 1
            elif len(accts) > 1 and ("cuentas" in q or (mentions_savings and mentions_checking) or cross_product):
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="account", fields=acct_fields, cardinality="all",
                    status="ready",
                ))
                n += 1
            elif len(accts) > 1 and not cross_product:
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="account", fields=acct_fields, status="needs_clarification",
                    unresolved_slots=["entity_ref"],
                    filters={"candidate_ids": [p.product_id for p in accts]},
                ))
                n += 1
            else:
                # Subtipo pedido ausente (p. ej. corriente en lab solo con ahorros)
                subtype = "CHECKING" if mentions_checking and not mentions_savings else (
                    "SAVINGS" if mentions_savings else None
                )
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="account", fields=acct_fields, status="ready",
                    filters={"account_subtype": subtype} if subtype else {},
                ))
                n += 1
        if mentions_card and not has_card_task:
            cards = []
            if snapshot is not None:
                cards = [
                    p for p in getattr(snapshot, "products", ()) or ()
                    if getattr(p, "product_type", "") == "CREDIT_CARD"
                    and str(getattr(p, "status", "")).lower() == "active"
                ]
            cfields = ["balance"]
            if "disponible" in q and "tarjeta" in q:
                cfields.append("available")
            # Multi-producto con 3 familias (cuenta+TC+préstamo): listar todas las TC.
            # Ahorros+TC solo: aclarar con cards (no listar silencioso).
            list_all_cards = len(cards) > 1 and (
                "tarjetas" in q
                or (mentions_account and mentions_loan)
            )
            if len(cards) != 1:
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="credit_card", fields=cfields,
                    cardinality="all" if list_all_cards else "single",
                    status="ready" if list_all_cards else ("needs_clarification" if len(cards) > 1 else "ready"),
                    unresolved_slots=[] if list_all_cards else (["entity_ref"] if len(cards) > 1 else []),
                    entity_ref=cards[0].product_id if len(cards) == 1 else None,
                    filters={"candidate_ids": [p.product_id for p in cards]} if len(cards) > 1 and not list_all_cards else {},
                ))
                n += 1
            else:
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="credit_card", fields=cfields,
                    entity_ref=cards[0].product_id, status="ready",
                ))
                n += 1
        # Si ya había tarea tarjeta single en cuenta+préstamo → forzar all
        if mentions_card and mentions_account and mentions_loan:
            for t in tasks:
                if t.object == "credit_card" and t.status == "needs_clarification":
                    t.cardinality = "all"
                    t.status = "ready"
                    t.unresolved_slots = []
                    t.entity_ref = None
        if mentions_loan and not has_loan_task:
            lfields: list[str] = []
            if "cuota" in q:
                lfields.append("installment_amount")
            if any(s in q for s in ("cuando", "cuándo", "vence", "fecha")):
                lfields.append("due_date")
            if any(s in q for s in ("debo", "pendiente", "saldo")):
                # Solo capital del préstamo si el «debo/saldo» no está anclado a tarjeta/cuenta
                if "debo de mi tarjeta" in q or "debo de mis tarjeta" in q:
                    pass
                elif "disponible" in q and "cuenta" in q and "prestamo" in q:
                    # «disponible en cuenta … cuota del préstamo» → no capital
                    if "capital" not in q and "pendiente de mi prestamo" not in q and "pendiente de mi préstamo" not in q and "pendiente de mis prestamo" not in q:
                        pass
                    else:
                        lfields.append("principal")
                else:
                    loan_part = q
                    if "prestamo" in q:
                        loan_part = q[q.find("prestamo"):]
                    elif "préstamo" in q:
                        loan_part = q[q.find("préstamo"):]
                    if "tarjeta" not in loan_part and "cuenta" not in loan_part and "principal" not in lfields:
                        if any(s in loan_part for s in ("debo", "pendiente", "saldo", "capital")):
                            lfields.append("principal")
            if not lfields:
                lfields = ["due_date"] if any(s in q for s in ("cuando", "cuándo", "vence")) else ["principal"]
            # Distinguir «cuándo vence la cuota» (solo fecha) vs «cuánto es la cuota» (monto)
            import re as _re_cuota
            cuota_m = _re_cuota.search(r".{0,50}cuota.{0,50}", q)
            cuota_ctx = cuota_m.group(0) if cuota_m else ""
            when_cuota = bool(cuota_ctx) and any(
                s in cuota_ctx for s in ("cuando", "cuándo", "vence", "tocar", "fecha")
            )
            amount_cuota = bool(cuota_ctx) and any(
                s in cuota_ctx for s in ("cuanto", "cuánto", "monto", "valor")
            )
            loan_tail = ""
            if "prestamo" in q:
                loan_tail = q[q.find("prestamo"):]
            elif "préstamo" in q:
                loan_tail = q[q.find("préstamo"):]
            if when_cuota and not amount_cuota:
                # Solo fecha de la próxima cuota
                lfields = ["due_date"]
            elif (
                "cuota" in q
                and any(s in q for s in ("vence", "cuando", "cuándo"))
                and "capital" not in loan_tail
                and not any(s in loan_tail for s in ("debo", "saldo", "pendiente"))
                and not amount_cuota
            ):
                lfields = ["due_date"]
            loans = []
            if snapshot is not None:
                loans = [
                    p for p in getattr(snapshot, "products", ()) or ()
                    if getattr(p, "product_type", "") == "LOAN"
                    and str(getattr(p, "status", "")).lower() == "active"
                ]
                if loan_hint_personal:
                    ids = {
                        ln.product_id for ln in (getattr(snapshot, "loans", None) or ())
                        if "personal" in _norm(ln.loan_type or "")
                    }
                    if ids:
                        loans = [p for p in loans if p.product_id in ids]
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="loan", fields=lfields,
                cardinality="all" if any(s in q for s in ("prestamos", "préstamos", "mis prestamo", "mis préstamo")) else "single",
                entity_ref=loans[0].product_id if len(loans) == 1 else None,
                status=(
                    "ready"
                    if len(loans) <= 1 or any(s in q for s in ("prestamos", "préstamos", "mis prestamo", "mis préstamo"))
                    else ("needs_clarification" if len(loans) > 1 else "ready")
                ),
                unresolved_slots=(
                    []
                    if len(loans) <= 1 or any(s in q for s in ("prestamos", "préstamos", "mis prestamo", "mis préstamo"))
                    else (["entity_ref"] if len(loans) > 1 else [])
                ),
            ))
            n += 1
        elif mentions_loan and has_loan_task and not split_done:
            # Completar campos de cuota/fecha si el match temprano solo trajo available/maturity
            import re as _re_cuota2
            cuota_m2 = _re_cuota2.search(r".{0,50}cuota.{0,50}", q)
            cuota_ctx2 = cuota_m2.group(0) if cuota_m2 else ""
            when_cuota2 = bool(cuota_ctx2) and any(
                s in cuota_ctx2 for s in ("cuando", "cuándo", "vence", "tocar", "fecha")
            )
            amount_cuota2 = bool(cuota_ctx2) and any(
                s in cuota_ctx2 for s in ("cuanto", "cuánto", "monto", "valor")
            )
            loan_tasks = [t for t in tasks if t.object == "loan"]
            for lt in loan_tasks:
                if when_cuota2 and not amount_cuota2:
                    lt.fields = [f for f in (lt.fields or []) if f != "installment_amount"]
                    if "due_date" not in (lt.fields or []):
                        lt.fields = list(lt.fields or []) + ["due_date"]
                elif "cuota" in q and "installment_amount" not in (lt.fields or []) and not when_cuota2:
                    lt.fields = list(lt.fields or []) + ["installment_amount"]
                if any(s in q for s in ("cuando", "cuándo", "vence", "pagarla")) and "due_date" not in (lt.fields or []):
                    lt.fields = list(lt.fields or []) + ["due_date"]
                if mentions_account or mentions_card:
                    lt.fields = [f for f in (lt.fields or []) if f not in ("available", "maturity")] or ["due_date"]
            # Eliminar tareas préstamo residuales solo con maturity/available en cruce multi-producto
            if mentions_account or mentions_card:
                tasks = [
                    t for t in tasks
                    if not (
                        t.object == "loan"
                        and set(t.fields or []).issubset({"maturity", "available"})
                    )
                ]

    # P09: todas las tarjetas + cuál tiene más disponible (un solo resumen; sin compare duplicado)
    if "tarjetas" in q and mentions_card and any(s in q for s in ("mas credito", "más crédito", "mas disponible", "más disponible", "cual de ellas", "cuál de ellas")):
        # Reemplazar tareas tarjeta single por all
        tasks = [t for t in tasks if t.object != "credit_card"]
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object="credit_card", fields=["balance", "available"], cardinality="all",
            status="ready",
        ))
        n += 1

    # P12: pagos próximos transversales
    if any(s in q for s in (
        "pago proximo", "pago próximo", "pagos proximos", "pagos próximos",
        "algun prestamo o tarjeta", "algún préstamo o tarjeta",
        "prestamo o tarjeta con un pago", "préstamo o tarjeta con un pago",
        "vence algo", "se me vence", "vence pronto", "vencen pronto",
        "estos dias", "estos días", "en estos dias", "en estos días",
        "prestamo o tarjeta", "préstamo o tarjeta",
        "prestamos o tarjetas", "préstamos o tarjetas",
    )) and any(s in q for s in (
        "vence", "pago", "pronto", "dias", "días", "cuanto", "cuánto", "pagar",
    )):
        # Evitar tareas tarjeta/préstamo genéricas que diluyen el escaneo
        tasks = [
            t for t in tasks
            if not (
                t.object in ("credit_card", "loan", "product")
                and t.action == "read_field"
                and not (t.filters or {}).get("upcoming_payments")
            )
        ]
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object="product", fields=["due_date", "installment_amount", "min_payment"],
            cardinality="all", filters={"upcoming_payments": True}, status="ready",
        ))
        n += 1

    elif (wants_available or wants_balance) and not any(
        t.domain == "personal" and (
            bool(t.entity_ref)
            or t.status == "needs_clarification"
            or t.cardinality == "all"
            or (
                t.object in ("credit_card", "account", "loan")
                and t.action == "read_field"
                and any(f in (t.fields or []) for f in ("balance", "available", "min_payment", "due_date", "payoff"))
            )
        )
        for t in tasks
    ):
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

    # ── Listado de portafolio personal ──
    if any(s in q for s in (
        "listame mis productos", "listame mis producto", "lista mis productos",
        "listar mis productos", "mis productos", "que productos tengo",
        "qué productos tengo", "cuales son mis productos", "cuáles son mis productos",
        "mostrar mis productos", "muestrame mis productos", "muéstrame mis productos",
        "ver mis productos", "productos activos", "mi portafolio",
    )) and not any(s in q for s in (
        "solicitar", "puedo solicitar", "catalogo", "catálogo", "del banco",
    )):
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="list",
            object="portfolio", fields=["list"], status="ready",
        ))
        n += 1

    # ── Certificados / DAPs (P15) ──
    if (
        mentions_dap or any(s in q for s in ("mis certificados", "todos los certificados"))
        or (personal_compare and any(s in q for s in ("certificado", "dap", "deposito", "depósito")))
    ) and not any(t.object == "term_deposit" for t in tasks):
        fields: list[str] = []
        if any(s in q for s in (
            "inverti", "invertí", "invertido", "cuanto inverti", "cuánto invertí",
            "capital invert", "monto invert", "balance", "saldo",
        )):
            # «compárame… balance» pide capital; «no necesito el balance» lo excluye abajo
            if not any(s in q for s in (
                "no el balance", "sin balance", "no necesito el balance",
                "no el capital", "sin capital",
            )):
                fields.append("principal")
        if "tasa" in q:
            fields.append("rate")
        if any(s in q for s in (
            "ha generado", "generado", "intereses acumul", "interes acumul",
            "interés acumul", "rendimiento",
        )):
            fields.append("interest_amount")
        if any(s in q for s in ("vence", "vencimiento")):
            fields.append("maturity")
        if not fields:
            fields = ["rate", "maturity", "principal"]
        excl: list[str] = []
        if any(s in q for s in (
            "no el balance", "sin balance", "no el capital", "sin capital", "pero no",
            "no muestres", "no mostrar", "sin mostrar", "no necesito el balance",
            "no necesito el capital",
        )):
            excl = ["balance", "capital", "principal"]
            fields = [f for f in fields if f not in ("principal", "balance", "capital")]
            if not fields:
                fields = ["rate", "maturity"]
        list_all = any(s in q for s in (
            "mis certificados", "todos los certificados", "listame", "listar",
            "certificados financieros",
        )) or personal_compare
        wants_earliest = any(s in q for s in (
            "primero en vencer", "vence primero", "mas pronto", "más pronto", "cual vence", "cuál vence",
        ))
        if personal_compare or list_all or wants_earliest:
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="term_deposit", fields=fields, cardinality="all",
                exclusions=excl, status="ready",
            ))
            n += 1
            if wants_earliest or (personal_compare and "vence" in q):
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="compare",
                    object="term_deposit", fields=["maturity"], cardinality="all",
                    filters={"operator": "earliest"}, exclusions=excl,
                    depends_on=[f"t{n-1}"], status="ready",
                ))
                n += 1
        else:
            daps = []
            if snapshot is not None:
                daps = [
                    p for p in getattr(snapshot, "products", ()) or ()
                    if getattr(p, "product_type", "") == "TERM_DEPOSIT"
                    and str(getattr(p, "status", "")).lower() == "active"
                ]
            if len(daps) <= 1:
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="term_deposit", fields=fields,
                    cardinality="single",
                    exclusions=excl,
                    entity_ref=daps[0].product_id if len(daps) == 1 else None,
                    status="ready",
                ))
            else:
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="term_deposit", fields=fields, cardinality="single",
                    exclusions=excl, status="needs_clarification",
                    unresolved_slots=["entity_ref"],
                    filters={"candidate_ids": [str(p.product_id) for p in daps]},
                ))
            n += 1

    # Payoff personal aunque no diga «préstamo» (follow-up tras proceso de cancelación)
    if (
        wants_loan_payoff
        and not mentions_card
        and not any(t.object == "loan" and "payoff" in (t.fields or []) for t in tasks)
    ):
        loans = []
        if snapshot is not None:
            loans = [
                p for p in getattr(snapshot, "products", ()) or ()
                if getattr(p, "product_type", "") == "LOAN"
                and str(getattr(p, "status", "")).lower() == "active"
            ]
        tasks.append(PlanTask(
            id=_next_id(n), domain="personal", action="read_field",
            object="loan", fields=["payoff"],
            entity_ref=loans[0].product_id if len(loans) == 1 else None,
            status="ready" if len(loans) == 1 else "needs_clarification",
            unresolved_slots=[] if len(loans) == 1 else ["entity_ref"],
        ))
        n += 1

    # Follow-up cargos → movimientos personales (MIX09/L08)
    if any(s in q for s in ("me cobraron", "me cobro", "cobraron alguno", "alguno recientemente")):
        if not any(t.fields == ["movements"] for t in tasks):
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object="credit_card", fields=["movements"], status="unsupported",
            ))
            n += 1

    # ── Ordinal / foco sobre compare_set de catálogo ──
    if session is not None and any(s in q for s in (
        "la segunda", "el segundo", "la primera", "el primero", "la tercera",
        "quedate", "quédate", "quedate con", "requisitos", "diferenc",
        "tienen diferente", "que tienen", "características", "caracteristicas",
        "de las tres", "hablame", "háblame",
    )):
        cset = list(getattr(session, "compare_set", None) or [])
        if cset and (
            "de las" in q or "de los" in q or "hablame" in q or "háblame" in q
            or "solo de" in q or "compar" in q or "quedate" in q or "quédate" in q
            or "requisitos" in q or "diferenc" in q or len(cset) >= 2
        ) and not any(s in q for s in ("prestamo", "préstamo", "tarjeta", "retomando")):
            # Pedir diferencias del conjunto vigente (sin ordinal)
            if any(s in q for s in ("requisitos", "diferenc", "distint", "caracter", "tienen diferente", "que tienen")) and not any(
                s in q for s in ("primer", "segund", "tercer", "de las tres")
            ):
                tasks.append(PlanTask(
                    id=_next_id(n), domain="catalog", action="compare",
                    object="product", fields=["features", "requirements"],
                    cardinality="compare",
                    entity_ref=",".join(cset),
                    filters={"compare_set": cset, "facet": "differences"},
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
        "volvamos", "volviendo a", "esa cuenta", "esa tarjeta", "ese prestamo", "ese préstamo",
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
        elif focus_id and any(s in q for s in ("esa cuenta", "esa tarjeta", "ese prestamo", "ese préstamo", "volvamos", "volviendo")):
            # Retomar foco personal tras excursión institucional (C1)
            obj_focus = {
                "ACCOUNT": "account",
                "CARD": "credit_card",
                "LOAN": "loan",
                "TERM_DEPOSIT": "term_deposit",
            }.get(str(focus_kind or ""), "account")
            field_focus = "available" if "disponible" in q else "balance"
            if obj_focus == "loan":
                field_focus = "rate" if "tasa" in q else "principal"
            tasks.append(PlanTask(
                id=_next_id(n), domain="personal", action="read_field",
                object=obj_focus, fields=[field_focus], entity_ref=focus_id,
                status="ready",
            ))
            n += 1
            transition = "continue"

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
        # USD / dólares sin producto en esa moneda → ausencia explícita
        if any(s in q for s in ("dolar", "dólar", "usd", "en dolares", "en dólares", "la de dolares", "la de dólares")):
            field = "available" if wants_available else "balance"
            accts_usd = []
            if snapshot is not None:
                accts_usd = [
                    p for p in getattr(snapshot, "products", ()) or ()
                    if str(getattr(p, "currency", "") or "").upper() == "USD"
                    and str(getattr(p, "status", "")).lower() == "active"
                ]
            if not accts_usd:
                tasks.append(PlanTask(
                    id=_next_id(1), domain="personal", action="read_field",
                    object="account", fields=[field],
                    filters={"currency": "USD"},
                    status="ready",
                ))
                plan = TurnPlan(tasks=tasks, transition=transition, source=source)
                return plan
        from genesis_cognitive.brain.azure_intent_brain import heuristic_intent
        from genesis_cognitive.brain.turn_plan import intent_packet_to_turn_plan

        pkt = heuristic_intent(raw, session)
        plan = intent_packet_to_turn_plan(pkt)
        plan.source = "adapter"
        return plan

    # Cuenta corriente / ahorros pedida de forma explícita: fijar subtipo y ambos saldos
    if mentions_checking and not mentions_savings and snapshot is not None:
        for t in tasks:
            if t.object == "account" and t.action == "read_field" and t.status == "ready":
                filt = dict(t.filters or {})
                filt["account_subtype"] = "CHECKING"
                t.filters = filt
                fields = list(t.fields or [])
                if wants_current and "balance" not in fields:
                    fields.insert(0, "balance")
                if (wants_available or "disponible" in q) and "available" not in fields:
                    fields.append("available")
                t.fields = [f for f in fields if f != "movements"]
    if mentions_savings and not mentions_checking and snapshot is not None:
        for t in tasks:
            if t.object == "account" and t.action == "read_field" and t.status == "ready":
                filt = dict(t.filters or {})
                filt["account_subtype"] = "SAVINGS"
                t.filters = filt

    # Plural «mis tarjetas» → listar todas (aunque el foco de sesión apunte a una)
    if "tarjetas" in q and mentions_card:
        for t in tasks:
            if t.object == "credit_card" and t.action == "read_field":
                t.cardinality = "all"
                t.entity_ref = None
                t.status = "ready"
                t.unresolved_slots = []

    # Ambas cuentas (ahorros + corriente) en la misma frase → responder las dos
    if mentions_savings and mentions_checking and snapshot is not None:
        accts_both = [
            p for p in getattr(snapshot, "products", ()) or ()
            if getattr(p, "product_type", "") in ("SAVINGS", "CHECKING")
            and str(getattr(p, "status", "")).lower() == "active"
        ]
        if len(accts_both) >= 2:
            acct_fields = ["balance"] if wants_current or "saldo" in q or "balance" in q else ["available"]
            if wants_available or "disponible" in q:
                if "available" not in acct_fields:
                    acct_fields.append("available")
            # Reemplazar tareas account ambiguas por all (no tocar unsupported/movements)
            tasks = [
                t for t in tasks
                if not (
                    t.object == "account"
                    and t.action == "read_field"
                    and t.status == "needs_clarification"
                )
            ]
            readable = [
                t for t in tasks
                if t.object == "account"
                and t.action == "read_field"
                and t.status == "ready"
                and "movements" not in (t.fields or [])
            ]
            if readable:
                keep = readable[0]
                keep.cardinality = "all"
                keep.status = "ready"
                keep.unresolved_slots = []
                keep.entity_ref = None
                keep.fields = [f for f in dict.fromkeys(list(keep.fields or []) + acct_fields) if f != "movements"]
                tasks = [t for t in tasks if t not in readable[1:]]
            elif not any(
                t.object == "account" and t.status == "ready" and "movements" not in (t.fields or [])
                for t in tasks
            ):
                tasks.append(PlanTask(
                    id=_next_id(n), domain="personal", action="read_field",
                    object="account", fields=acct_fields, cardinality="all",
                    status="ready",
                ))
                n += 1

    # Fusionar tareas personales duplicadas del mismo objeto/entity (p. ej. available×2)
    merged_tasks: list[PlanTask] = []
    index: dict[tuple, int] = {}
    for t in tasks:
        if t.domain != "personal" or t.action != "read_field":
            merged_tasks.append(t)
            continue
        # No fusionar unsupported (movimientos) con lecturas ready
        if t.status == "unsupported" or "movements" in (t.fields or []):
            merged_tasks.append(t)
            continue
        key = (t.object, t.entity_ref or "", t.cardinality, t.status, t.action)
        if key in index:
            prev = merged_tasks[index[key]]
            fields = list(prev.fields or [])
            for f in t.fields or []:
                if f not in fields and f != "movements":
                    fields.append(f)
            prev.fields = fields
            if t.exclusions:
                prev.exclusions = list(dict.fromkeys(list(prev.exclusions or []) + list(t.exclusions)))
            if t.filters:
                filt = dict(prev.filters or {})
                filt.update(t.filters)
                prev.filters = filt
        else:
            index[key] = len(merged_tasks)
            merged_tasks.append(t)
    tasks = merged_tasks
    for i, t in enumerate(tasks, start=1):
        t.id = f"t{i}"

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
