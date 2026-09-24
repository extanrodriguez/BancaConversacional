"""Ejecutor multi-tarea de TurnPlan → evidencia por tarea + respuesta compuesta."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from decimal import Decimal
from typing import Any

from genesis_cognitive.brain.intent_types import GroundedResult, IntentPacket
from genesis_cognitive.brain.turn_plan import PlanTask, TurnPlan
from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot


@dataclass
class TaskEvidence:
    task_id: str
    domain: str
    status: str  # available | absent | needs_clarification | unsupported | error | refused
    entity: str | None = None
    field_name: str | None = None
    value: str | None = None
    currency: str | None = None
    source: str = "snapshot"
    text: str = ""
    extras: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class PlanExecutionResult:
    status: str
    text: str
    intent_id: str
    evidences: list[TaskEvidence]
    actions: list[dict] = dc_field(default_factory=list)
    options: list[dict] | None = None
    suggestions: list[dict] | None = None
    account_ref: str | None = None
    route: str = "personal"
    trace: dict[str, Any] = dc_field(default_factory=dict)
    # Mutaciones de estado propuestas (el caller hace commit CAS)
    pending_tasks: list[dict] | None = None
    compare_set: list[str] | None = None
    clear_pending_action: bool = False
    set_product_focus: tuple[str, str, str] | None = None  # kind, id, intent
    last_knowledge_topic: str | None = None
    preserve_pending_action: bool = False


# Mapeo autorizado catálogo → criterio de portafolio (existencia MIX07 / V3-13)
# product_ids: coincidencia exacta; product_types: solo si el mapeo lo autoriza explícitamente
# multicredito: servicio, no ítem de portafolio aislado
_CATALOG_TO_PORTFOLIO: dict[str, dict[str, Any]] = {
    "multicredito": {"kind": "service_on", "requires_types": ("CREDIT_CARD",), "confirm": "unknown_service"},
    "credito_diferido": {"kind": "service_on", "requires_types": ("CREDIT_CARD",), "confirm": "unknown_service"},
    "cuotas_bsc": {"kind": "service_on", "requires_types": ("CREDIT_CARD",), "confirm": "unknown_service"},
    "visa_platinum": {"kind": "product_ids", "ids": (), "confirm": "unmapped"},  # sin IDs → desconocido
    "visa_infinite": {"kind": "product_ids", "ids": (), "confirm": "unmapped"},
    "visa_gold": {"kind": "product_ids", "ids": (), "confirm": "unmapped"},
    "visa_classic": {"kind": "product_ids", "ids": (), "confirm": "unmapped"},
    "visa_joven": {"kind": "product_ids", "ids": (), "confirm": "unmapped"},
    "cuenta_ahorros": {"kind": "product_types", "types": ("SAVINGS",), "confirm": "type"},
    "cuenta_corriente": {"kind": "product_types", "types": ("CHECKING",), "confirm": "type"},
    "cuenta_nomina": {"kind": "product_types", "types": ("PAYROLL",), "confirm": "type"},
    "prestamo_personal": {"kind": "product_types", "types": ("LOAN",), "confirm": "type"},
}


def _money(val: Decimal | None, ccy: str | None) -> str | None:
    if val is None:
        return None
    from genesis_cognitive.context.response_formatting import format_money

    return format_money(val, ccy or "DOP")


def _faq_text(snapshot: CustomerContextSnapshot | None, question: str, session: Any) -> str | None:
    try:
        from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail

        hit = apply_faq_guardrail(snapshot, question, session=session) if snapshot else None
        if hit and (hit[2] or "").strip():
            return hit[2]
    except Exception:
        pass
    # Glosario local versionado (no inventar en Python sin procedencia)
    try:
        from pathlib import Path
        import json
        import os

        path = os.getenv("GENESIS_GLOSSARY_PATH") or str(
            Path(__file__).resolve().parents[3] / "data" / "kb_glossary_local_v31.json"
        )
        # parents: brain -> genesis_cognitive -> src -> root = parents[2]? 
        # __file__ = .../src/genesis_cognitive/brain/plan_executor.py
        # parents[0]=brain, [1]=genesis_cognitive, [2]=src, [3]=root
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        qn = (question or "").lower()
        for e in data.get("entries") or []:
            kws = [str(k).lower() for k in (e.get("keywords") or [])]
            if any(k in qn for k in kws):
                ans = (e.get("answer") or "").strip()
                if ans:
                    return ans
    except Exception:
        pass
    if snapshot is None:
        try:
            from genesis_cognitive.router.faq_guardrail import match_faq

            m = match_faq(question)
            if m and m.get("answer"):
                return str(m["answer"])
        except Exception:
            pass
    return None


def _execute_refuse(task: PlanTask) -> TaskEvidence:
    if task.object == "secret":
        return TaskEvidence(
            task_id=task.id, domain=task.domain, status="refused",
            field_name="auth_secret",
            text=(
                "Por seguridad no debo recibir ni almacenar tu PIN, OTP, CVV ni contraseñas. "
                "No uses esos datos en el chat. Si necesitas autenticarte, usa los canales oficiales del banco."
            ),
            source="security",
        )
    return TaskEvidence(
        task_id=task.id, domain=task.domain, status="refused",
        field_name="ownership",
        text=(
            "Solo puedo consultar información de productos asociados a tu sesión autenticada. "
            "No puedo mostrar saldos ni datos de otra persona."
        ),
        source="security",
    )


def _execute_institutional(
    task: PlanTask,
    snapshot: CustomerContextSnapshot | None,
    session: Any,
) -> TaskEvidence:
    parts = task.fields or ["mision"]
    # Construir pregunta que active fusión misión+visión
    labels = {"mision": "misión", "vision": "visión", "valores": "valores",
              "available_balance": "qué significa saldo disponible"}
    q = " y ".join(labels.get(p, p) for p in parts)
    if task.object == "glossary":
        q = "qué significa saldo disponible"
        if "interest_rate" in (task.fields or []) or "tasa" in "+".join(task.fields or []):
            q = "qué significa la tasa de interés"
    if task.action == "compare" and set(parts) >= {"mision", "vision"}:
        q = "misión y visión"
    text = _faq_text(snapshot, q, session)
    if not text and snapshot is None:
        try:
            from genesis_cognitive.router.faq_guardrail import match_faq

            m = match_faq(q)
            if m and m.get("answer"):
                text = str(m["answer"])
        except Exception:
            text = None
    if not text and task.object == "glossary":
        return TaskEvidence(
            task_id=task.id, domain="institutional", status="absent",
            field_name="+".join(parts),
            text=(
                "No recuperé una definición aprobada en la base de conocimiento local "
                "para ese término. No inventé un glosario."
            ),
            source="retrieval_gap",
        )
    if text and task.action == "compare":
        # Solo anexar síntesis si ambas partes vinieron de FAQ
        text = (
            "Misión y visión recuperadas:\n\n"
            + text
            + "\n\nDiferencia sustentada por las entradas anteriores: la misión describe el "
            "propósito presente; la visión, la aspiración a futuro."
        )
    if text:
        return TaskEvidence(
            task_id=task.id, domain="institutional", status="available",
            field_name="+".join(parts), value=None, text=text, source="faq",
        )
    return TaskEvidence(
        task_id=task.id, domain="institutional", status="absent",
        field_name="+".join(parts),
        text="No encontré esa definición en la base de conocimiento disponible.",
        source="retrieval_gap",
    )


def _execute_catalog_or_process(
    task: PlanTask,
    snapshot: CustomerContextSnapshot | None,
    session: Any,
) -> TaskEvidence:
    if task.action == "compare" and task.object == "cancellation":
        text = _faq_text(snapshot, "proceso de cancelación tarjeta y préstamo", session)
        if not text:
            return TaskEvidence(
                task_id=task.id, domain="process", status="absent",
                field_name="cancellation_process",
                text=(
                    "No recuperé evidencia aprobada que compare los procesos de cancelación "
                    "de tarjeta y préstamo. No consulté montos de cancelación de productos tuyos."
                ),
                source="retrieval_gap",
            )
        return TaskEvidence(
            task_id=task.id, domain="process", status="available",
            field_name="cancellation_process", text=text, source="faq",
        )
    if task.fields and "min_payment" in task.fields:
        text = _faq_text(snapshot, "qué es el pago mínimo de tarjeta de crédito", session)
        if not text:
            return TaskEvidence(
                task_id=task.id, domain="catalog", status="absent",
                field_name="min_payment",
                text=(
                    "No recuperé una definición aprobada de pago mínimo en la base local. "
                    "No seleccioné una tarjeta personal."
                ),
                source="retrieval_gap",
            )
        return TaskEvidence(
            task_id=task.id, domain="catalog", status="available",
            field_name="min_payment", text=text, source="faq",
        )
    # Comparación ordenada de catálogo con facetas (disponibilidad por celda)
    if task.action == "compare" and task.domain == "catalog":
        refs = list((task.filters or {}).get("compare_set") or [])
        if not refs and task.entity_ref:
            refs = [x for x in str(task.entity_ref).split(",") if x]
        if len(refs) < 2:
            return TaskEvidence(
                task_id=task.id, domain="catalog", status="needs_clarification",
                text="¿Cuáles productos del catálogo deseas comparar?",
                extras={"compare_set": refs},
            )
        lines = ["Comparación de catálogo (orden de mención / conjunto vigente):"]
        for i, r in enumerate(refs):
            facet = _faq_text(snapshot, f"condiciones de {r.replace('_', ' ')}", session)
            if facet:
                lines.append(f"{i+1}. **{r.replace('_', ' ').title()}** — evidencia recuperada.")
                lines.append(facet[:280] + ("…" if len(facet) > 280 else ""))
            else:
                lines.append(
                    f"{i+1}. **{r.replace('_', ' ').title()}** — "
                    "faceta no disponible en fuentes locales (celda sin evidencia)."
                )
        lines.append("Puedes pedir «la segunda» del conjunto vigente o agregar otro producto.")
        return TaskEvidence(
            task_id=task.id, domain="catalog", status="available",
            text="\n".join(lines),
            extras={"compare_set": refs},
            source="catalog_compare",
        )
    # Define catálogo (selección ordinal o «qué es»)
    ref = task.entity_ref or task.object
    ordinal = (task.filters or {}).get("ordinal")
    label = str(ref or "").replace("_", " ").title()
    text = _faq_text(snapshot, f"condiciones de {str(ref).replace('_', ' ')}", session)
    header = f"Seleccionaste **{label}**"
    if ordinal:
        header += f" (posición {ordinal} del conjunto vigente)"
    header += "."
    if not text:
        return TaskEvidence(
            task_id=task.id, domain="catalog", status="absent",
            entity=ref,
            text=(
                f"{header} No recuperé evidencia aprobada adicional para este producto "
                "de catálogo. No implica consulta de saldos personales."
            ),
            source="retrieval_gap",
            extras={"catalog_ref": ref, "ordinal": ordinal, "compare_set": (task.filters or {}).get("compare_set")},
        )
    # Anteponer identidad del producto aunque el FAQ sea genérico
    body = f"{header}\n{text}"
    return TaskEvidence(
        task_id=task.id, domain="catalog", status="available",
        entity=ref, text=body, source="faq",
        extras={"catalog_ref": ref, "ordinal": ordinal, "compare_set": (task.filters or {}).get("compare_set")},
    )


def _execute_existence(
    task: PlanTask,
    snapshot: CustomerContextSnapshot,
) -> TaskEvidence:
    ref = (task.filters or {}).get("catalog_ref") or task.entity_ref
    # Mapeo de prueba autorizado (V3-13): filters.authorized_personal_id
    auth_pid = (task.filters or {}).get("authorized_personal_id")
    if auth_pid:
        owned = [p for p in snapshot.products if p.product_id == auth_pid]
        if owned:
            return TaskEvidence(
                task_id=task.id, domain="personal", status="available",
                entity=auth_pid, value="present",
                text=f"Sí: según el mapeo autorizado, tienes el producto {auth_pid} en tu portafolio.",
                source="existence_authorized_map",
            )
        return TaskEvidence(
            task_id=task.id, domain="personal", status="absent",
            entity=str(auth_pid),
            text=(
                f"El mapeo autorizado apunta a {auth_pid}, pero no aparece en el "
                "snapshot consultado."
            ),
            source="existence_authorized_map",
        )
    if not ref:
        return TaskEvidence(
            task_id=task.id, domain="personal", status="needs_clarification",
            text="¿A qué producto del catálogo te refieres para verificar si lo tienes?",
        )
    key = str(ref).strip().lower().replace(" ", "_")
    if "multicredit" in key or key == "multicredito":
        key = "multicredito"
    mapping = _CATALOG_TO_PORTFOLIO.get(key)
    if mapping is None:
        return TaskEvidence(
            task_id=task.id, domain="personal", status="absent",
            entity=key,
            text=(
                f"No tengo un mapeo autorizado entre «{ref}» y tu portafolio. "
                "No puedo afirmar ni negar que lo tengas; la ausencia de mapeo "
                "no equivale a que el producto no exista."
            ),
            source="existence_unmapped",
        )
    kind = mapping.get("kind")
    if kind == "service_on":
        req = mapping.get("requires_types") or ()
        cards = [
            p for p in snapshot.products
            if p.product_type in req and str(p.status).lower() == "active"
        ]
        return TaskEvidence(
            task_id=task.id, domain="personal", status="absent" if not cards else "available",
            entity=key,
            text=(
                f"«{ref}» es un servicio asociado a tarjetas, no un ítem aislado del portafolio. "
                + (
                    f"Tienes {len(cards)} tarjeta(s) activa(s); la contratación del servicio "
                    "no aparece como producto separado en este contexto."
                    if cards
                    else "No veo tarjetas activas; no puedo confirmar ese servicio."
                )
            ),
            source="existence_service",
        )
    if kind == "product_ids":
        ids = tuple(mapping.get("ids") or ())
        if not ids:
            return TaskEvidence(
                task_id=task.id, domain="personal", status="absent",
                entity=key,
                text=(
                    f"No hay identificadores autorizados que vinculen «{ref}» con tu portafolio. "
                    "No confirmo posesión por similitud de nombre (p. ej. otra Visa)."
                ),
                source="existence_unmapped",
            )
        owned = [p for p in snapshot.products if p.product_id in ids]
        if not owned:
            return TaskEvidence(
                task_id=task.id, domain="personal", status="absent",
                entity=key,
                text=f"En el portafolio consultado no aparece el producto mapeado a «{ref}».",
                source="existence",
            )
        return TaskEvidence(
            task_id=task.id, domain="personal", status="available",
            entity=owned[0].product_id,
            text=f"Sí: tienes {owned[0].alias or owned[0].product_id} asociado a «{ref}».",
            source="existence",
        )
    types = tuple(mapping.get("types") or ())
    owned = [
        p for p in snapshot.products
        if p.product_type in types and str(p.status).lower() == "active"
    ]
    if not owned:
        return TaskEvidence(
            task_id=task.id, domain="personal", status="absent",
            entity=key,
            text=f"En tu portafolio autenticado no aparece un producto del tipo asociado a «{ref}».",
            source="existence",
        )
    labels = ", ".join((p.alias or p.product_id) for p in owned[:5])
    return TaskEvidence(
        task_id=task.id, domain="personal", status="available",
        entity=key, value=str(len(owned)),
        text=f"Sí: en tu portafolio hay {len(owned)} producto(s) del tipo asociado a «{ref}»: {labels}.",
        source="existence",
    )


def _execute_personal_fields(
    task: PlanTask,
    snapshot: CustomerContextSnapshot,
    question: str,
    session: Any,
) -> list[TaskEvidence]:
    from genesis_cognitive.brain.grounded_executor import execute_grounded

    evidences: list[TaskEvidence] = []
    fields = task.fields or ["balance"]
    if task.status == "unsupported":
        if fields and fields[0] == "movements":
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="unsupported",
                field_name="movements",
                text=(
                    "Puedo consultar tu saldo, pero el historial de movimientos "
                    "no está disponible en este canal con las capacidades actuales. "
                    "No inventé transacciones."
                ),
                source="capability",
            )]
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="unsupported",
            field_name=fields[0] if fields else None,
            text=(
                "Ese campo no está soportado para este tipo de producto en el contexto actual. "
                "No lo convertí a una consulta de cuenta."
            ),
            source="capability",
        )]
    if task.status == "needs_clarification":
        obj = task.object
        label = {
            "credit_card": "tarjeta",
            "account": "cuenta",
            "loan": "préstamo",
            "term_deposit": "certificado",
        }.get(obj, "producto")
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="needs_clarification",
            text=f"¿Sobre cuál {label} quieres esa información?",
            extras={"missing": task.unresolved_slots},
        )]

    # Exclusiones P15
    excl = set(task.exclusions or [])

    # Multi-moneda: listar por moneda, sin total mixto
    if (
        task.object == "account"
        and task.cardinality == "all"
        and (task.filters or {}).get("multi_currency")
    ):
        accts = [
            p for p in snapshot.products
            if p.product_type in ("SAVINGS", "CHECKING", "PAYROLL")
            and str(p.status).lower() == "active"
        ]
        if not accts:
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="absent",
                text="No tienes cuentas activas en el portafolio.",
            )]
        by_ccy: dict[str, list] = {}
        for p in accts:
            by_ccy.setdefault(p.currency or "DOP", []).append(p)
        lines: list[str] = []
        for ccy, items in by_ccy.items():
            known: list[Decimal] = []
            missing = 0
            for p in items:
                if p.available_balance is None:
                    missing += 1
                    lines.append(
                        f"• {p.alias or p.product_id}: disponible ausente ({ccy})"
                    )
                else:
                    known.append(p.available_balance)
                    lines.append(
                        f"• {p.alias or p.product_id}: {_money(p.available_balance, ccy)} disponible"
                    )
            if known and missing == 0:
                subtotal = sum(known, Decimal("0"))
                lines.append(f"Total {ccy} (completo): {_money(subtotal, ccy)}")
            elif known:
                subtotal = sum(known, Decimal("0"))
                lines.append(
                    f"Subtotal {ccy} conocido: {_money(subtotal, ccy)} "
                    f"({missing} cuenta(s) sin dato; no tratados como cero)."
                )
            else:
                lines.append(f"Total {ccy}: no calculable (todos los valores ausentes).")
        lines.append(
            "No calculé un total único entre monedas: no hay base de conversión autorizada."
        )
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="available",
            field_name="available", text="\n".join(lines), source="snapshot",
        )]

    if task.object == "term_deposit" and task.cardinality in ("all", "compare"):
        daps = [
            p for p in snapshot.products
            if p.product_type == "TERM_DEPOSIT" and str(p.status).lower() == "active"
        ]
        if not daps:
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="absent",
                text="No tienes certificados a plazo activos en el portafolio.",
            )]
        if task.action == "compare" and (task.filters or {}).get("operator") == "earliest":
            dated = [(p, p.maturity_date) for p in daps if p.maturity_date]
            missing = [p for p in daps if not p.maturity_date]
            if not dated:
                return [TaskEvidence(
                    task_id=task.id, domain="personal", status="absent",
                    field_name="maturity",
                    text=(
                        "No puedo comparar vencimientos: ninguna fecha de vencimiento "
                        "está disponible en el portafolio."
                    ),
                    source="snapshot",
                )]
            dated.sort(key=lambda x: x[1] or "")
            first = dated[0][0]
            warn = ""
            if missing:
                warn = (
                    f" Advertencia: {len(missing)} certificado(s) sin fecha no "
                    "participaron en el mínimo."
                )
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="available",
                entity=first.product_id, field_name="maturity", value=first.maturity_date,
                text=(
                    f"Entre los certificados con fecha válida, el que vence primero es "
                    f"{first.alias or first.product_id} (vencimiento {first.maturity_date})."
                    + warn
                ),
                source="snapshot",
            )]
        lines: list[str] = []
        for p in daps:
            bits: list[str] = [p.alias or p.product_id]
            if "rate" in fields and p.interest_rate is not None:
                bits.append(f"tasa {p.interest_rate}%")
            if "maturity" in fields and p.maturity_date:
                bits.append(f"vence {p.maturity_date}")
            # Excluir balance/capital del texto
            if "balance" not in excl and "capital" not in excl:
                pass  # no agregar
            lines.append(" — ".join(bits))
        body = "Tus certificados:\n" + "\n".join(f"• {ln}" for ln in lines)
        # Guardrail: no mencionar balance/capital ni tarjetas
        low = body.lower()
        assert "tarjeta" not in low
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="available",
            field_name="+".join(fields), text=body, source="snapshot",
            extras={"excluded": list(excl), "count": len(daps)},
        )]

    # Una evidencia por campo (P01 multi-campo)
    for fld in fields:
        scope = "all" if task.cardinality == "all" else "single"
        # Pregunta sintética para no dejar que continuity reescriba el campo
        # a partir del texto de selección ordinal («el segundo»).
        synth_q = {
            "rate": "¿cuál es la tasa?",
            "available": "¿cuánto tengo disponible?",
            "balance": "¿cuánto debo?" if task.object == "credit_card" else "¿cuál es el saldo?",
            "due_date": "¿cuál es la fecha de pago?",
            "principal": "¿cuál es el capital pendiente?",
            "maturity": "¿cuál es el vencimiento?",
        }.get(fld, question)
        pkt = IntentPacket(
            "personal",
            task.object if task.object != "catalog_mapped" else "mixed",
            fld,
            scope=scope,
            confidence=0.95,
            product_hint_digits=task.entity_ref,
            rewritten_question=synth_q,
            source="plan_executor",
            rationale=f"plan:{task.id}:{fld}",
        )
        result = execute_grounded(pkt, snapshot, question=synth_q, session=session)
        st = "available"
        if result.status == "CLARIFICATION_REQUIRED":
            st = "needs_clarification"
        elif result.status in ("UNSUPPORTED", "NON_OPERATIONAL"):
            st = "unsupported"
        elif not (result.text or "").strip():
            st = "absent"
        evidences.append(TaskEvidence(
            task_id=f"{task.id}.{fld}",
            domain="personal",
            status=st,
            entity=result.account_ref or task.entity_ref,
            field_name=fld,
            text=result.text or "",
            source="grounded",
            extras={"intent_id": result.intent_id, "status": result.status},
        ))
    return evidences


def execute_turn_plan(
    plan: TurnPlan,
    snapshot: CustomerContextSnapshot | None,
    question: str,
    session: Any | None = None,
) -> PlanExecutionResult:
    """Ejecuta todas las tareas del plan y compone respuesta + mutaciones de estado."""
    evidences: list[TaskEvidence] = []
    actions: list[dict] = []
    compare_set_out: list[str] | None = None
    pending_out: list[dict] | None = None
    focus_out: tuple[str, str, str] | None = None
    knowledge_topic: str | None = None
    preserve_pending = False
    clear_pending = False

    for task in plan.tasks:
        if task.action == "refuse":
            evidences.append(_execute_refuse(task))
            continue
        if task.domain == "institutional":
            ev = _execute_institutional(task, snapshot, session)
            evidences.append(ev)
            knowledge_topic = (ev.field_name or "institutional")[:120]
            # Excursión institucional: no borrar pendiente personal
            if session is not None and getattr(session, "pending_action", None) is not None:
                preserve_pending = True
            continue
        if task.domain in ("catalog", "process"):
            ev = _execute_catalog_or_process(task, snapshot, session)
            evidences.append(ev)
            if ev.extras.get("compare_set") is not None:
                compare_set_out = list(ev.extras["compare_set"])
            if ev.extras.get("catalog_ref"):
                knowledge_topic = str(ev.extras["catalog_ref"])
            continue
        if task.action == "check_existence":
            if snapshot is None:
                evidences.append(TaskEvidence(
                    task_id=task.id, domain="personal", status="error",
                    text="No hay contexto personal cargado para verificar existencia.",
                ))
            else:
                evidences.append(_execute_existence(task, snapshot))
            continue
        if task.domain == "personal":
            if snapshot is None:
                evidences.append(TaskEvidence(
                    task_id=task.id, domain="personal", status="error",
                    text="Necesito tu contexto de productos para esa consulta personal.",
                ))
                continue
            evs = _execute_personal_fields(task, snapshot, question, session)
            evidences.extend(evs)
            for ev in evs:
                if ev.status == "needs_clarification":
                    pending_out = pending_out or []
                    display_order: list[str] = []
                    if snapshot is not None and task.object == "credit_card":
                        display_order = [
                            p.product_id for p in snapshot.products
                            if p.product_type == "CREDIT_CARD"
                            and str(p.status).lower() == "active"
                        ]
                    elif snapshot is not None and task.object == "loan":
                        display_order = [
                            p.product_id for p in snapshot.products
                            if p.product_type == "LOAN"
                            and str(p.status).lower() == "active"
                        ]
                    pending_out.append({
                        "task_id": task.id,
                        "object": task.object,
                        "fields": list(task.fields or []),
                        "original_question": question,
                        "display_order": display_order,
                    })
                if ev.status == "available" and ev.entity and task.object == "credit_card":
                    focus_out = ("CARD", ev.entity, "CREDIT_CARD_DETAIL_READ")
                    clear_pending = True
                elif ev.status == "available" and ev.entity and task.object == "account":
                    focus_out = ("ACCOUNT", ev.entity, "ACCOUNT_BALANCE_READ")
                    clear_pending = True
                elif ev.status == "available" and ev.entity and task.object == "loan":
                    focus_out = ("LOAN", ev.entity, "LOAN_DETAIL_READ")
                    clear_pending = True
            continue
        # chitchat / none
        evidences.append(TaskEvidence(
            task_id=task.id, domain=task.domain, status="available",
            text="", source="noop",
        ))

    # Componer texto: toda tarea visible
    blocks: list[str] = []
    overall = "VALID_CONTRACT"
    intent = "TURN_PLAN_MULTI"
    account_ref = None
    for ev in evidences:
        if ev.text:
            blocks.append(ev.text.strip())
        if ev.status == "needs_clarification":
            overall = "CLARIFICATION_REQUIRED"
            intent = "CLARIFICATION"
        elif ev.status == "refused" and overall == "VALID_CONTRACT":
            intent = "SECURITY_GUARDRAIL"
        if ev.entity and account_ref is None:
            account_ref = ev.entity
        if ev.extras.get("intent_id") and intent == "TURN_PLAN_MULTI":
            intent = str(ev.extras["intent_id"])

    # Si hay aclaración Y datos sustentados: mantener VALID parcial + aclaración en texto
    has_data = any(e.status == "available" and e.text for e in evidences)
    has_clarify = any(e.status == "needs_clarification" for e in evidences)
    if has_data and has_clarify:
        overall = "VALID_CONTRACT"  # responde lo sustentado y aclara lo pendiente en el mismo texto
        intent = "TURN_PLAN_PARTIAL"

    text = "\n\n".join(blocks).strip()
    if not text:
        text = "No pude completar la consulta con la información disponible."
        overall = "VALID_CONTRACT"

    # Acciones sintéticas para canal
    actions.append({
        "sequence": 1,
        "intent_id": intent,
        "capability_candidate": "TURN_PLAN",
        "selected_route": "PERSONAL_READ" if any(e.domain == "personal" for e in evidences) else "KNOWLEDGE",
        "detected_entities": {"account_ref": account_ref},
        "missing_requirements": (
            ["account_ref"] if overall == "CLARIFICATION_REQUIRED" else []
        ),
        "depends_on": [],
        "confidence": 0.9,
    })

    return PlanExecutionResult(
        status=overall,
        text=text,
        intent_id=intent,
        evidences=evidences,
        actions=actions,
        account_ref=account_ref,
        route="knowledge" if all(e.domain in ("institutional", "catalog", "process") for e in evidences) else "personal",
        trace={
            "plan": plan.to_dict(),
            "task_count": len(plan.tasks),
            "task_statuses": {e.task_id: e.status for e in evidences},
            "interpreter": plan.source,
            "transition": plan.transition,
        },
        pending_tasks=pending_out,
        compare_set=compare_set_out,
        clear_pending_action=clear_pending and not preserve_pending,
        set_product_focus=focus_out,
        last_knowledge_topic=knowledge_topic,
        preserve_pending_action=preserve_pending,
    )


def to_grounded_result(result: PlanExecutionResult) -> GroundedResult:
    return GroundedResult(
        status=result.status,
        text=result.text,
        intent_id=result.intent_id,
        account_ref=result.account_ref,
        actions=result.actions,
        route=result.route,
        trace=result.trace,
    )
