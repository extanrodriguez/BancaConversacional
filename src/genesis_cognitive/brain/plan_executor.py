"""Ejecutor multi-tarea de TurnPlan → evidencia por tarea + respuesta compuesta."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from decimal import Decimal
from typing import Any

from genesis_cognitive.brain.intent_types import GroundedResult, IntentPacket
from genesis_cognitive.brain.turn_plan import PlanTask, TurnPlan
from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot


_CONTACT_CHANNELS_BLOCK = (
    "• Centro de Contacto: [809.726.1000](tel:+18097261000)\n"
    "• Correo: [serviciobancanet@bsc.com.do](mailto:serviciobancanet@bsc.com.do)\n"
    "• Web: [bsc.com.do](https://bsc.com.do/)\n"
    "• Centro de Negocios o BSC en Línea"
)


def _contact_channels_reply(prefix: str = "") -> str:
    """Fallback UX cuando falta dato o la consulta no se pudo completar."""
    head = (prefix or "No tengo esa información disponible en este momento.").strip()
    return (
        f"{head} Para más información contacte las líneas de atención del banco:\n\n"
        f"{_CONTACT_CHANNELS_BLOCK}"
    )


@dataclass
class TaskEvidence:
    task_id: str
    domain: str
    status: str  # available | partial | absent | needs_clarification | unsupported | error | refused
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


def _preserve_multi_product_pending(
    session: Any,
    object_kind: str,
    *,
    exclude_entity: str | None = None,
) -> list[dict] | None:
    """Re-emite pending multi-opción intacto (todas las cards del set inicial).

    La exclusión del producto recién respondido se aplica solo al armar options
    del turno; el display_order completo se conserva para poder volver a mostrar
    las demás (incluidas las ya consultadas antes) en el siguiente turno.
    """
    if session is None:
        return None
    out: list[dict] = []
    for pt in getattr(session, "pending_tasks", None) or []:
        if not isinstance(pt, dict):
            continue
        order = [str(x) for x in (pt.get("display_order") or [])]
        if len(order) < 2:
            continue
        obj = str(pt.get("object") or "")
        if object_kind and obj and obj != object_kind and obj != "product":
            continue
        kept = dict(pt)
        kept["display_order"] = order
        # Track last answered for this turn's options filter (optional hint)
        if exclude_entity:
            kept["last_answered_entity"] = exclude_entity
        out.append(kept)
    return out or None


def _strip_leading_greeting(text: str, display_name: str | None) -> str:
    t = (text or "").strip()
    if not t:
        return t
    name = (display_name or "").strip()
    if name and t.lower().startswith(name.lower() + ","):
        t = t[len(name) + 1 :].lstrip(" \n")
    # Quitar negritas markdown residuales del canal
    t = t.replace("**", "")
    return t.strip()


def _normalize_evidence_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("**", "")
    return " ".join(t.split())


def _dedupe_evidence_texts(evidences: list[TaskEvidence]) -> list[TaskEvidence]:
    """Elimina evidencias cuyo texto ya apareció (resúmenes all + compare)."""
    seen: set[str] = set()
    out: list[TaskEvidence] = []
    multi_summary_text = ""
    for ev in evidences:
        if ev.field_name == "multi_summary" and (ev.text or "").strip():
            multi_summary_text = _normalize_evidence_text(ev.text)
            break
    for ev in evidences:
        raw = (ev.text or "").strip()
        if not raw:
            out.append(ev)
            continue
        key = _normalize_evidence_text(raw)
        # Compare residual si el resumen all ya incluye el ganador
        if (
            multi_summary_text
            and ev.field_name == "available"
            and "más crédito disponible" in key
            and "más crédito disponible" in multi_summary_text
        ):
            continue
        if key in seen:
            continue
        # Subconjunto casi idéntico (mismo párrafo repetido)
        if any(key in prev or prev in key for prev in seen if len(key) > 40 and len(prev) > 40):
            continue
        seen.add(key)
        out.append(ev)
    return out


def _compose_multi_field_bullets(
    evidences: list[TaskEvidence],
    snapshot: CustomerContextSnapshot | None,
) -> str | None:
    """Un saludo + viñetas cuando hay ≥2 campos personales del mismo producto."""
    personal = [
        e for e in evidences
        if e.domain == "personal"
        and e.status in ("available", "unsupported")
        and (e.text or "").strip()
        and e.field_name
        and e.field_name not in ("list", "count", "presence", "multi_summary")
    ]
    if len(personal) < 2:
        return None
    entities = {e.entity for e in personal if e.entity}
    if len(entities) > 1:
        return None
    if any(
        e.status == "needs_clarification"
        or (e.domain != "personal" and (e.text or "").strip())
        for e in evidences
    ):
        return None
    name = getattr(snapshot, "display_name", None) if snapshot is not None else None
    lines: list[str] = []
    seen_bodies: set[str] = set()
    for ev in personal:
        body = _strip_leading_greeting(ev.text, name).rstrip(" .")
        if not body:
            continue
        norm = _normalize_evidence_text(body)
        if norm in seen_bodies:
            continue
        seen_bodies.add(norm)
        lines.append(f"- {body}.")
    if len(lines) < 2:
        return None
    greeting = f"{name},\n\n" if name else ""
    return greeting + "\n".join(lines)


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


_CATALOG_PRODUCT_MARKERS: dict[str, tuple[str, ...]] = {
    "visa_platinum": ("platinum", "platino"),
    "visa_infinite": ("infinite",),
    "visa_gold": ("gold", " oro", "visa oro"),
    "visa_joven": ("joven",),
    "visa_classic": ("clasica", "classic"),
    "visa_clasica": ("clasica", "classic"),
    "multicredito": ("multicredit", "credito diferido"),
    "cuenta_corriente": ("corriente",),
    "cuenta_ahorros": ("ahorro", "ahorros"),
    "cuenta_nomina": ("nomina", "nómina"),
}


def _norm_catalog(s: str) -> str:
    import unicodedata

    t = (s or "").lower().replace("_", " ")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return t


def _catalog_ref_key(ref: str | None) -> str | None:
    if not ref:
        return None
    n = _norm_catalog(ref).replace(" ", "_")
    aliases = {
        "visa_platino": "visa_platinum",
        "platinum": "visa_platinum",
        "infinite": "visa_infinite",
        "gold": "visa_gold",
        "oro": "visa_gold",
        "joven": "visa_joven",
        "visa_joven_credito": "visa_joven",
    }
    if n in _CATALOG_PRODUCT_MARKERS:
        return n
    return aliases.get(n) or (n if n.startswith("visa_") or n.startswith("cuenta_") else None)


def _evidence_applies_to_catalog_product(
    *,
    question: str,
    text: str,
    ref: str | None = None,
    topic: str | None = None,
) -> bool:
    """True solo si el texto/topic corresponde al producto pedido (no Platinum←Joven)."""
    wanted = _catalog_ref_key(ref)
    qn = _norm_catalog(question)
    if not wanted:
        for key, markers in _CATALOG_PRODUCT_MARKERS.items():
            if any(m.strip() in qn for m in markers if len(m.strip()) >= 4):
                # Preferir el más específico presente en la pregunta
                if key.replace("visa_", "") in qn or key.replace("_", " ") in qn:
                    wanted = key
                    break
                if any(m.strip() in qn for m in markers):
                    wanted = wanted or key
    if not wanted:
        return True
    markers = _CATALOG_PRODUCT_MARKERS.get(wanted) or ()
    blob = _norm_catalog(f"{topic or ''} {text}")
    has_wanted = any(m.strip() in blob for m in markers if m.strip())
    # Productos rivales explícitos en el cuerpo sin el pedido → rechazo
    for other, om in _CATALOG_PRODUCT_MARKERS.items():
        if other == wanted:
            continue
        has_other = any(m.strip() in blob for m in om if len(m.strip()) >= 4)
        if has_other and not has_wanted:
            return False
    return bool(has_wanted)


def _unwrap_retrieval_text(text: str | None) -> tuple[str | None, str]:
    """Separa marcador interno de Azure Search del cuerpo visible."""
    if not text:
        return None, "faq"
    if text.startswith("__AZURE_SEARCH__\n"):
        return text.split("\n", 1)[1], "azure_search"
    return text, "faq"


def _faq_text(
    snapshot: CustomerContextSnapshot | None,
    question: str,
    session: Any,
    *,
    required_product_ref: str | None = None,
) -> str | None:
    # Preferir match_faq tipado (Joven/fallecidos) antes del guardrail genérico
    def _accept(answer: str, topic: str | None = None) -> str | None:
        if not (answer or "").strip():
            return None
        if not _evidence_applies_to_catalog_product(
            question=question, text=answer, ref=required_product_ref, topic=topic,
        ):
            return None
        return answer

    import re as _re
    import unicodedata

    def _nq(s: str) -> str:
        t = (s or "").lower()
        t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
        return t

    qn = _nq(question)
    # Glosario saldo disponible: corpus MD de matriz (Fila N) no es definición
    wants_avail_glossary = bool(
        _re.search(r"(que|qué)\s+(significa|es)\s+(el\s+)?saldo\s+disponible", qn)
        or _re.search(r"definici[oó]n\s+(del?\s+)?saldo\s+disponible", qn)
        or qn.strip() in {"qué significa saldo disponible", "que significa saldo disponible"}
    )
    wants_glossary_first = wants_avail_glossary or any(
        s in qn
        for s in (
            "que es ", "que son ", "que significa", "definicion",
            "explicame", "hablame de", "cuentame", "son lo mismo", "es lo mismo",
            "diferencia", "como se calcula", "como funciona", "para que sirve",
        )
    )

    def _is_search_contaminant(q: str, ans: str, meta: dict | None) -> bool:
        """Rechaza hits Azure Search genéricos ajenos a la pregunta (p.ej. Documento digital)."""
        aq = _nq(q)
        aa = _nq((ans or "")[:160])
        title = _nq(str((meta or {}).get("title") or (meta or {}).get("topic") or ""))
        if "documento digital" in aa or "documento digital" in title:
            if "documento digital" not in aq and "documento electronico" not in aq:
                return True
        return False

    def _try_azure_search(q: str) -> tuple[str | None, dict | None]:
        try:
            from genesis_cognitive.rag.azure_search_retrieve import (
                best_knowledge_answer,
                search_enabled,
            )
            from genesis_cognitive.rag.grounding_verifier import product_filter_terms

            if not search_enabled():
                return None, None
            pf = product_filter_terms(required_product_ref)
            # Conocimiento de producto: preferir fichas; glosario/proc si no hay ref
            doc_types = (
                ["product_knowledge", "definition"]
                if required_product_ref
                else ["product_knowledge", "definition", "procedure", "scoped_editorial_summary", "public_reference"]
            )
            res = best_knowledge_answer(
                q, top=5, product_filter=pf, document_types=doc_types
            )
            if not res or res.get("status") != "SEARCH_REAL_PASS":
                return None, res
            ans = (res.get("answer") or "").strip()
            if _is_search_contaminant(q, ans, res):
                return None, res
            ok = _accept(ans, topic=str(res.get("title") or ""))
            if ok:
                return ok, res
        except Exception:
            return None, None
        return None, None

    # Glosario / definición: FAQ local primero (Azure Search contaminaba con
    # «Documento digital»). Resto: Search real antes de FAQ.
    search_ans, search_meta = (None, None)
    if not wants_glossary_first:
        search_ans, search_meta = _try_azure_search(question)
        if search_ans and not wants_avail_glossary:
            return f"__AZURE_SEARCH__\n{search_ans}"

    if wants_avail_glossary:
        # Preferir Search si hay definición conceptual; si no, glosario local.
        if search_ans and not any(
            s in search_ans.lower()
            for s in ("rd$", "terminada en", "tu tarjeta", "tienes ")
        ):
            return f"__AZURE_SEARCH__\n{search_ans}"
        try:
            from pathlib import Path
            import json
            import os

            path = os.getenv("GENESIS_GLOSSARY_PATH") or str(
                Path(__file__).resolve().parents[3] / "data" / "kb_glossary_local_v31.json"
            )
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for e in data.get("entries") or []:
                if str(e.get("id") or "") == "glos-available-balance" or "saldo disponible" in [
                    str(k).lower() for k in (e.get("keywords") or [])
                ]:
                    ans = (e.get("answer") or "").strip()
                    ok = _accept(ans, topic=str(e.get("topic") or "saldo disponible"))
                    if ok:
                        return ok
        except Exception:
            pass

    try:
        from genesis_cognitive.router.faq_guardrail import match_faq

        if any(s in qn for s in (
            "joven", "fallec", "reclam", "misi", "visi",
            "multicredit", "cargo", "cancel", "platinum", "infinite", "gold",
            "cuenta corriente", "cuenta de ahorro", "cuenta ahorr",
        )) and not wants_avail_glossary:
            m = match_faq(question)
            if m and m.get("answer"):
                topic = _nq(str(m.get("topic") or ""))
                if topic in {"cliente", "clientes"} and "cliente" not in qn.split()[:3] and "joven" in qn:
                    pass
                else:
                    ok = _accept(str(m["answer"]), topic=str(m.get("topic") or ""))
                    if ok:
                        return ok
    except Exception:
        pass
    try:
        from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail

        hit = apply_faq_guardrail(snapshot, question, session=session) if snapshot else None
        if hit and (hit[2] or "").strip():
            ok = _accept(hit[2], topic=None)
            if ok:
                return ok
    except Exception:
        pass
    # Reintento Search si FAQ no aportó (p. ej. misión/visión)
    if not search_ans:
        search_ans, search_meta = _try_azure_search(question)
    if search_ans:
        return f"__AZURE_SEARCH__\n{search_ans}"
    # Glosario local versionado (no inventar en Python sin procedencia)
    try:
        from pathlib import Path
        import json
        import os

        path = os.getenv("GENESIS_GLOSSARY_PATH") or str(
            Path(__file__).resolve().parents[3] / "data" / "kb_glossary_local_v31.json"
        )
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        qn2 = (question or "").lower()
        for e in data.get("entries") or []:
            kws = [str(k).lower() for k in (e.get("keywords") or [])]
            if any(k in qn2 for k in kws):
                ans = (e.get("answer") or "").strip()
                ok = _accept(ans, topic=str(e.get("topic") or ""))
                if ok:
                    return ok
    except Exception:
        pass
    try:
        from genesis_cognitive.rag.kb_package_ingest import local_retrieve

        loc = local_retrieve(
            question,
            limit=3,
            required_product=required_product_ref,
        )
        for hit in loc or []:
            title = str(hit.get("title") or "").strip()
            body = str(hit.get("content") or "").strip()
            if not body:
                continue
            if title.lower() == "cliente" and "cliente" not in (question or "").lower():
                continue
            ok = _accept(body, topic=title)
            if ok:
                return ok
    except Exception:
        pass
    if snapshot is None:
        try:
            from genesis_cognitive.router.faq_guardrail import match_faq

            m = match_faq(question)
            if m and m.get("answer"):
                ok = _accept(str(m["answer"]), topic=str(m.get("topic") or ""))
                if ok:
                    return ok
        except Exception:
            pass
    return None


def _contrast_catalog_attributes(
    a_label: str,
    a_txt: str,
    b_label: str,
    b_txt: str,
) -> list[str]:
    """Contrasta atributos equivalentes con valores concretos cuando existen."""
    import re

    attrs = [
        ("segmento / público", ("segmento", "dirigid", "joven", "premium", "empresarial", "persona")),
        ("requisitos", ("requisito", "requer", "necesita", "ingresos", "edad", "antiguedad", "años")),
        ("beneficios", ("beneficio", "puntos", "millas", "cashback", "seguro", "acceso")),
        ("costos / tarifas", ("tarifa", "comision", "membres", "anualidad", "cargo")),
        ("límite / cupo", ("limite", "límite", "cupo", "credito disponible")),
    ]
    lines: list[str] = []
    an = _norm_catalog(a_txt)
    bn = _norm_catalog(b_txt)

    def _snip(raw: str, keys_: tuple[str, ...]) -> str:
        low = raw.lower()
        for k in keys_:
            i = low.find(k)
            if i >= 0:
                return re.sub(r"\s+", " ", raw[max(0, i - 20): i + 100]).strip()
        return ""

    def _value_or_excerpt(raw: str, keys_: tuple[str, ...]) -> str:
        snip = _snip(raw, keys_)
        if snip:
            return snip[:110]
        # Si hay ficha pero el keyword no aparece: extracto inicial usable
        clean = re.sub(r"\s+", " ", (raw or "").strip())
        return clean[:110] if clean else ""

    for name, keys in attrs:
        a_hit = any(k in an for k in keys)
        b_hit = any(k in bn for k in keys)
        sa = _value_or_excerpt(a_txt, keys) if (a_hit or a_txt.strip()) else ""
        sb = _value_or_excerpt(b_txt, keys) if (b_hit or b_txt.strip()) else ""
        if a_hit and b_hit and sa and sb:
            if _norm_catalog(sa) != _norm_catalog(sb):
                lines.append(
                    f"- **{name}**: **{a_label}** → «{sa}»; **{b_label}** → «{sb}»."
                )
            else:
                lines.append(
                    f"- **{name}**: ambos productos coinciden en el extracto «{sa[:80]}»."
                )
        elif a_hit and sa and not b_hit:
            # Mostrar valor concreto del lado disponible; declarar ausencia del otro
            lines.append(
                f"- **{name}**: **{a_label}** → «{sa}»; "
                f"en la ficha recuperada de **{b_label}** no aparece este atributo."
            )
        elif b_hit and sb and not a_hit:
            lines.append(
                f"- **{name}**: **{b_label}** → «{sb}»; "
                f"en la ficha recuperada de **{a_label}** no aparece este atributo."
            )
    if not lines and (a_txt.strip() or b_txt.strip()):
        # Ambos tienen texto: contrastar extractos generales bajo atributo «descripción»
        ea = re.sub(r"\s+", " ", a_txt.strip())[:120]
        eb = re.sub(r"\s+", " ", b_txt.strip())[:120]
        if ea and eb:
            lines.append(
                f"- **descripción / condiciones**: **{a_label}** → «{ea}»; "
                f"**{b_label}** → «{eb}»."
            )
    if not lines:
        lines.append(
            f"- No hallé atributos equivalentes contrastables entre {a_label} y {b_label} "
            "en las fichas recuperadas; no inventé diferencias."
        )
    return lines


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


def _execute_count(task: PlanTask, snapshot: CustomerContextSnapshot | None) -> TaskEvidence:
    """Cuenta productos activos del tipo pedido. No inventa y no llama al modelo."""
    if snapshot is None:
        return TaskEvidence(
            task_id=task.id, domain="personal", status="error",
            field_name="count",
            text="Necesito tu contexto de productos para contarte cuántos tienes.",
        )
    from genesis_cognitive.context.product_display import display_label_in_context

    kind = task.object
    products = [
        p for p in snapshot.products
        if str(getattr(p, "status", "")).lower() == "active"
    ]
    if kind == "loan":
        pool = [p for p in products if p.product_type == "LOAN"]
        noun = "préstamo"
    elif kind == "credit_card":
        pool = [p for p in products if p.product_type == "CREDIT_CARD"]
        noun = "tarjeta de crédito"
    elif kind == "term_deposit":
        pool = [p for p in products if p.product_type == "TERM_DEPOSIT"]
        noun = "certificado"
    elif kind == "account":
        pool = [p for p in products if p.product_type in ("SAVINGS", "CHECKING", "PAYROLL")]
        noun = "cuenta"
    else:
        pool = products
        noun = "producto"
    g = f"{snapshot.display_name}, " if snapshot.display_name else ""
    n = len(pool)
    if n == 0:
        text = f"{g}no tienes {noun}s activos en tu portafolio."
    else:
        labels = [display_label_in_context(p, pool) for p in pool]
        listed = "; ".join(labels)
        if noun == "préstamo":
            plural = "préstamo" if n == 1 else "préstamos"
        elif noun == "tarjeta de crédito":
            plural = "tarjeta de crédito" if n == 1 else "tarjetas de crédito"
        elif noun == "certificado":
            plural = "certificado" if n == 1 else "certificados"
        elif noun == "cuenta":
            plural = "cuenta" if n == 1 else "cuentas"
        else:
            plural = "producto" if n == 1 else "productos"
        text = f"{g}tienes **{n}** {plural} activo{'s' if n != 1 else ''}: {listed}."
    return TaskEvidence(
        task_id=task.id, domain="personal", status="available",
        field_name="count", text=text, source="snapshot",
        extras={"count": n, "object": kind},
    )


def _execute_institutional(
    task: PlanTask,
    snapshot: CustomerContextSnapshot | None,
    session: Any,
    *,
    question: str = "",
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
        # Características de producto mal clasificadas como glosario
        raw = (question or "").strip()
        if raw and any(s in raw.lower() for s in ("joven", "caracter", "visa", "reclam", "fallec")):
            q = raw
    if task.action == "compare" and set(parts) >= {"mision", "vision"}:
        q = "misión y visión"
    if (question or "").strip() and any(s in (question or "").lower() for s in ("misi", "visi")):
        q = question
    text = _faq_text(snapshot, q, session)
    text, evidence_source = _unwrap_retrieval_text(text)
    if not text and snapshot is None:
        try:
            from genesis_cognitive.router.faq_guardrail import match_faq

            m = match_faq(q)
            if m and m.get("answer"):
                text = str(m["answer"])
                evidence_source = "faq"
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
            field_name="+".join(parts), value=None, text=text, source=evidence_source,
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
    *,
    question: str = "",
) -> TaskEvidence:
    # Cancelación ambigua al estilo Foundry KB: ¿cuenta, tarjeta, préstamo o certificado?
    if (
        task.domain == "process"
        and task.object == "cancellation"
        and task.status == "needs_clarification"
    ):
        text = (
            "Para orientarte con el proceso de cancelación, ¿a qué producto te refieres?\n\n"
            "• Cuenta\n"
            "• Tarjeta de crédito\n"
            "• Préstamo\n"
            "• Certificado / depósito a plazo\n\n"
            "Indica el tipo y te detallo el proceso. También puedes llamar al "
            "Centro de Contacto [809.726.1000](tel:+18097261000) o visitar un Centro de Negocios."
        )
        return TaskEvidence(
            task_id=task.id, domain="process", status="needs_clarification",
            field_name="cancellation_clarify", text=text, source="cancellation_disambiguation",
            extras={"clarify_families": list((task.filters or {}).get("clarify_families") or [])},
        )
    # Cancelación de préstamos: no sustituir por Multicrédito / crédito diferido.
    # No usar Azure Search genérico («CANCELACIÓN DE PRODUCTOS») — contamina L09/MIX10.
    if task.domain == "process" and task.object == "loan_cancellation":
        text = (
            "Para cancelar un **préstamo** (personal, hipotecario u otro crédito de consumo), "
            "debes solicitarlo en un centro de negocios o por los canales oficiales del banco, "
            "liquidar el saldo de cancelación vigente y obtener la carta de saldo. "
            "Esta orientación aplica a préstamos, no a otros productos de financiamiento del banco. "
            "Si quieres el monto exacto para cancelar el tuyo, pídelo en el siguiente turno."
        )
        try:
            from genesis_cognitive.router.faq_guardrail import match_faq

            m = match_faq("cancelación de préstamos personales Banco Santa Cruz")
            if m and (m.get("answer") or "").strip():
                cand = str(m.get("answer") or "").strip()
                tn = cand.lower()
                if not any(
                    s in tn
                    for s in (
                        "multicrédito",
                        "multicredito",
                        "crédito diferido",
                        "credito diferido",
                        "cuotas bsc",
                        "cancelación de productos",
                        "cancelacion de productos",
                    )
                ) and any(s in tn for s in ("préstamo", "prestamo", "hipotec")):
                    text = cand
        except Exception:
            pass
        return TaskEvidence(
            task_id=task.id, domain="process", status="available",
            field_name="loan_cancellation_process", text=text, source="loan_cancellation_scoped",
            extras={"product_family": "loan", "rejected_multicredit_substitution": True},
        )
    # Procesos KB (reclamaciones, fallecidos, cancelación genérica)
    if task.domain == "process" and task.action in ("process", "define") and task.object != "loan_cancellation":
        q = str((task.filters or {}).get("query") or question or "").strip()
        if q:
            try:
                from genesis_cognitive.router.reclamacion_guardrail import (
                    apply_reclamacion_guardrail,
                    is_reclamacion_question,
                )
                if is_reclamacion_question(q):
                    hit = apply_reclamacion_guardrail(snapshot, q)
                    if hit is not None:
                        st, _acts, txt, _sug = hit
                        return TaskEvidence(
                            task_id=task.id,
                            domain="process",
                            status=(
                                "needs_clarification"
                                if st == "CLARIFICATION_REQUIRED"
                                else "available"
                            ),
                            field_name="reclamacion",
                            text=txt or "",
                            source="reclamacion_guardrail",
                        )
            except Exception:
                pass
            text = _faq_text(snapshot, q, session)
            if text:
                return TaskEvidence(
                    task_id=task.id, domain="process", status="available",
                    field_name="process", text=text, source="faq",
                )
        return TaskEvidence(
            task_id=task.id, domain="process", status="absent",
            field_name="process",
            text=(
                "No recuperé evidencia aprobada de ese proceso en la base de "
                "conocimiento disponible."
            ),
            source="retrieval_gap",
        )
    if task.action == "compare" and task.object == "cancellation":
        text = _faq_text(
            snapshot,
            str((task.filters or {}).get("query") or "proceso de cancelación de préstamo y tarjeta"),
            session,
        )
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
    if task.domain == "process" and task.object == "cancellation":
        q = str((task.filters or {}).get("query") or question or "proceso de cancelación de préstamos").strip()
        text = _faq_text(snapshot, q, session)
        if not text:
            text = _faq_text(snapshot, "proceso de cancelación crédito diferido", session)
        if text:
            return TaskEvidence(
                task_id=task.id, domain="process", status="available",
                field_name="cancellation_process", text=text, source="faq",
            )
        return TaskEvidence(
            task_id=task.id, domain="process", status="absent",
            field_name="cancellation_process",
            text=(
                "No recuperé evidencia aprobada del proceso de cancelación en la base "
                "de conocimiento disponible. No consulté montos personales."
            ),
            source="retrieval_gap",
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
        facet = str((task.filters or {}).get("facet") or "features")
        want_diff = facet in ("differences", "requirements", "features") or any(
            s in (question or "").lower() for s in ("diferente", "diferencia", "características", "caracteristicas")
        )
        lines = ["Comparación de catálogo (orden de mención / conjunto vigente):"]
        recovered: list[tuple[str, str]] = []
        for i, r in enumerate(refs):
            label = r.replace("_", " ").title()
            q_feat = f"características de {r.replace('_', ' ')}"
            facet_text = _faq_text(
                snapshot, q_feat, session, required_product_ref=r,
            )
            if not facet_text:
                facet_text = _faq_text(
                    snapshot,
                    f"condiciones de {r.replace('_', ' ')}",
                    session,
                    required_product_ref=r,
                )
            if facet_text and not _evidence_applies_to_catalog_product(
                question=q_feat, text=facet_text, ref=r,
            ):
                facet_text = None
            if facet_text:
                recovered.append((label, facet_text))
                lines.append(f"{i+1}. **{label}** — evidencia recuperada (producto verificado).")
                # Budget compare: conservar condiciones (no truncar a 320)
                clip = 2800
                lines.append(facet_text[:clip] + ("…" if len(facet_text) > clip else ""))
            else:
                lines.append(
                    f"{i+1}. **{label}** — "
                    "faceta no disponible o evidencia no aplicable a este producto "
                    "(celda sin evidencia válida)."
                )
        if want_diff and len(recovered) >= 2:
            lines.append("")
            lines.append("Diferencias por atributos equivalentes:")
            a_label, a_txt = recovered[0]
            b_label, b_txt = recovered[1]
            lines.extend(_contrast_catalog_attributes(a_label, a_txt, b_label, b_txt))
            if len(recovered) > 2:
                lines.append(
                    f"- El conjunto incluye también: "
                    + ", ".join(f"**{lab}**" for lab, _ in recovered[2:])
                    + "."
                )
        elif want_diff and len(recovered) < 2:
            lines.append(
                "No pude contrastar diferencias: faltó evidencia local aplicable "
                "para al menos dos productos del conjunto."
            )
        # Verifier de grounding: producto + atributo; parcial ≠ completo
        try:
            from genesis_cognitive.rag.grounding_verifier import verify_compare_set

            attr = "features"
            if facet in ("requirements",):
                attr = "requirement"
            elif facet in ("differences",):
                attr = "features"
            g = verify_compare_set(refs, recovered=recovered, attribute=attr)
            grounding_extras = g.as_dict()
            if not g.ok:
                lines.append("")
                lines.append(
                    "Grounding incompleto: sin evidencia verificable para: "
                    + ", ".join(g.missing)
                    + ". No invento atributos faltantes."
                )
                for note in g.notes[:3]:
                    lines.append(f"- {note}")
        except Exception:
            grounding_extras = {"ok": None, "error": "grounding_verifier_unavailable"}
        lines.append("Puedes pedir «la segunda» del conjunto vigente o agregar otro producto.")
        # Completo solo si todos los refs tienen evidencia grounded
        all_grounded = bool(grounding_extras.get("ok")) and len(recovered) >= len(refs)
        if all_grounded and (not want_diff or len(recovered) >= 2):
            status = "available"
        elif recovered:
            status = "partial"
            lines.insert(
                1,
                "_(Comparación parcial: no todos los productos/atributos tienen evidencia.)_",
            )
        else:
            status = "absent"
        return TaskEvidence(
            task_id=task.id, domain="catalog", status=status,
            text="\n".join(lines),
            extras={
                "compare_set": refs,
                "facet": facet,
                "grounding": grounding_extras,
                "compare_completeness": "complete" if all_grounded else "partial",
            },
            source="catalog_compare",
        )
    # Define catálogo (selección ordinal o «qué es»)
    ref = task.entity_ref or task.object
    ordinal = (task.filters or {}).get("ordinal")
    label = str(ref or "").replace("_", " ").title()
    q_catalog = (
        str((task.filters or {}).get("query") or question or "").strip()
        or f"características de {str(ref).replace('_', ' ')}"
    )
    text = _faq_text(snapshot, q_catalog, session, required_product_ref=str(ref) if ref else None)
    text, cat_source = _unwrap_retrieval_text(text)
    if not text and ref:
        text = _faq_text(
            snapshot,
            f"características de {str(ref).replace('_', ' ')}",
            session,
            required_product_ref=str(ref),
        )
        text, cat_source = _unwrap_retrieval_text(text)
    if text and ref and not _evidence_applies_to_catalog_product(
        question=q_catalog, text=text, ref=str(ref),
    ):
        text = None
    header = f"Seleccionaste **{label}**"
    if ordinal:
        header += f" (posición {ordinal} del conjunto vigente)"
    header += "."
    if not text:
        return TaskEvidence(
            task_id=task.id, domain="catalog", status="absent",
            entity=ref,
            text=(
                f"{header} No recuperé evidencia aprobada **aplicable a este producto** "
                "de catálogo. No implica consulta de saldos personales."
            ),
            source="retrieval_gap",
            extras={"catalog_ref": ref, "ordinal": ordinal, "compare_set": (task.filters or {}).get("compare_set")},
        )
    # Anteponer identidad del producto aunque el FAQ sea genérico
    body = f"{header}\n{text}"
    return TaskEvidence(
        task_id=task.id, domain="catalog", status="available",
        entity=ref, text=body, source=cat_source,
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

    # Resolver object genérico «product» al tipo real del portafolio
    if task.object == "product" and task.entity_ref:
        hit = next(
            (
                p for p in snapshot.products
                if p.product_id == task.entity_ref
            ),
            None,
        )
        if hit is not None:
            task.object = {
                "LOAN": "loan",
                "TERM_DEPOSIT": "term_deposit",
                "CREDIT_CARD": "credit_card",
                "SAVINGS": "account",
                "CHECKING": "account",
                "PAYROLL": "account",
            }.get(hit.product_type, "account")

    if (task.filters or {}).get("portfolio_gap") and not task.entity_ref:
        field = fields[0] if fields else "balance"
        obj = task.object or "product"
        if field == "rate":
            if obj == "loan":
                msg = "No tienes préstamos con tasa de interés visibles en tu portafolio."
            elif obj == "term_deposit":
                msg = "No tienes certificados con tasa de interés visibles en tu portafolio."
            elif obj == "credit_card":
                msg = "No tienes tarjetas de crédito con tasa visibles en tu portafolio."
            else:
                msg = "No tienes productos con tasa de interés visibles en tu portafolio."
        elif field == "maturity":
            if obj == "term_deposit":
                msg = "No tienes certificados con fecha de vencimiento visibles en tu portafolio."
            elif obj == "loan":
                msg = "No tienes préstamos con fecha de vencimiento visibles en tu portafolio."
            else:
                msg = "No tienes productos con fecha de vencimiento visibles en tu portafolio."
        elif field in ("balance", "principal") and obj == "credit_card":
            msg = "No tienes tarjetas de crédito con saldo adeudado en tu portafolio."
        elif field in ("due_date", "installment_amount") and obj == "loan":
            msg = "No tienes préstamos personales con cuota próxima de pago en tu portafolio."
        elif field in ("balance", "available") and obj == "account":
            msg = "No tienes cuentas activas con ese saldo en tu portafolio."
        else:
            msg = "No encontré ese producto en tu portafolio activo."
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="absent",
            field_name=field, text=msg, source="portfolio_gap",
        )]

    # Listado de portafolio (PORTFOLIO_LIST) — no pasa por campos unitarios
    if task.action == "list" or task.object == "portfolio" or (
        fields == ["list"] and task.object in ("portfolio", "product", "none")
    ):
        from genesis_cognitive.context.product_display import build_portfolio_listing, filter_active

        active = filter_active(snapshot)
        if not active:
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="absent",
                field_name="list",
                text=(
                    f"{snapshot.display_name}, no tienes productos activos visibles "
                    "en tu portafolio."
                    if snapshot.display_name
                    else "No tienes productos activos visibles en tu portafolio."
                ),
                source="portfolio_list",
            )]
        text = build_portfolio_listing(snapshot)
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="available",
            field_name="list",
            text=text,
            source="portfolio_list",
            extras={"intent_id": "PORTFOLIO_LIST", "count": len(active)},
        )]

    if task.status == "unsupported":
        if fields and fields[0] == "movements":
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="unsupported",
                field_name="movements",
                text=_contact_channels_reply(
                    "Puedo consultar tu saldo, pero el historial de movimientos "
                    "no está disponible en este momento."
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
        field = (task.fields or ["balance"])[0]
        candidate_ids = list((task.filters or {}).get("candidate_ids") or [])
        pool: list = []
        if snapshot is not None and candidate_ids:
            by_id = {p.product_id: p for p in snapshot.products}
            pool = [by_id[i] for i in candidate_ids if i in by_id]
        if pool:
            from genesis_cognitive.context.app_channel import build_product_disambiguation_question
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="needs_clarification",
                field_name=field,
                text=build_product_disambiguation_question(pool, field=field),
                extras={"missing": task.unresolved_slots, "candidate_ids": candidate_ids},
            )]
        label = {
            "credit_card": "tarjeta",
            "account": "cuenta",
            "loan": "préstamo",
            "term_deposit": "certificado",
            "product": "producto",
        }.get(obj, "producto")
        if field == "rate":
            text = f"¿De cuál de tus productos con tasa de interés quieres consultar?"
        else:
            text = f"¿Sobre cuál {label} quieres esa información?"
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="needs_clarification",
            field_name=field,
            text=text,
            extras={"missing": task.unresolved_slots},
        )]

    # Subtipo pedido ausente del portafolio (p. ej. corriente) — resultado de negocio
    subtype = (task.filters or {}).get("account_subtype")
    if task.object == "account" and subtype and not task.entity_ref:
        matches = [
            p for p in snapshot.products
            if p.product_type == subtype and str(p.status).lower() == "active"
        ]
        if not matches:
            label = {
                "CHECKING": "cuenta corriente",
                "SAVINGS": "cuenta de ahorros",
                "PAYROLL": "cuenta de nómina",
            }.get(str(subtype), "cuenta de ese tipo")
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="absent",
                field_name=(task.fields or ["balance"])[0],
                text=f"No tienes {label} activa en tu portafolio.",
                source="portfolio_gap",
                extras={"requested_subtype": subtype},
            )]
        if len(matches) == 1:
            task.entity_ref = matches[0].product_id
            task.status = "ready"

    # Moneda pedida ausente (USD) — no inventar ni convertir
    want_ccy = str((task.filters or {}).get("currency") or "").upper()
    if task.object == "account" and want_ccy and not task.entity_ref:
        matches_ccy = [
            p for p in snapshot.products
            if str(p.currency or "").upper() == want_ccy
            and p.product_type in ("SAVINGS", "CHECKING", "PAYROLL")
            and str(p.status).lower() == "active"
        ]
        if not matches_ccy:
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="absent",
                field_name=(task.fields or ["balance"])[0],
                text=f"No tienes cuentas activas en {want_ccy} en tu portafolio.",
                source="portfolio_gap",
                extras={"requested_currency": want_ccy},
            )]
        if len(matches_ccy) == 1:
            task.entity_ref = matches_ccy[0].product_id
            task.status = "ready"

    # Exclusiones P15
    excl = set(task.exclusions or [])

    # Tasa en tarjeta cuando el snapshot trae interest_rate
    if task.object == "credit_card" and fields == ["rate"] and task.entity_ref:
        card = next((p for p in snapshot.products if p.product_id == task.entity_ref), None)
        if card is not None and card.interest_rate is not None:
            from genesis_cognitive.context.product_display import display_label
            g = f"{snapshot.display_name}, " if snapshot.display_name else ""
            return [TaskEvidence(
                task_id=f"{task.id}.rate", domain="personal", status="available",
                entity=card.product_id, field_name="rate",
                value=str(card.interest_rate),
                text=(
                    f"{g}la tasa de interés de tu {display_label(card)} "
                    f"es **{card.interest_rate}%** anual."
                ),
                source="snapshot",
                extras={"intent_id": "CREDIT_CARD_DETAIL_READ"},
            )]
        return [TaskEvidence(
            task_id=f"{task.id}.rate", domain="personal", status="absent",
            entity=task.entity_ref, field_name="rate",
            text="No tengo la tasa de esa tarjeta en el contexto cargado.",
            source="portfolio_gap",
        )]

    # Detalle completo (consulta/revisa sin campo puntual)
    if fields == ["detail"] and task.entity_ref:
        from genesis_cognitive.context.product_display import display_label
        from genesis_cognitive.context.response_formatting import (
            build_rich_card_detail,
            build_rich_deposit_detail,
            build_rich_loan_detail,
        )
        g = f"{snapshot.display_name}, " if snapshot.display_name else ""
        prod = next((p for p in snapshot.products if p.product_id == task.entity_ref), None)
        if prod is not None and task.object == "credit_card":
            return [TaskEvidence(
                task_id=f"{task.id}.detail", domain="personal", status="available",
                entity=prod.product_id, field_name="detail",
                text=f"{g.rstrip()}\n{build_rich_card_detail(prod)}".strip(),
                source="snapshot",
                extras={"intent_id": "CREDIT_CARD_DETAIL_READ"},
            )]
        if prod is not None and task.object == "term_deposit":
            return [TaskEvidence(
                task_id=f"{task.id}.detail", domain="personal", status="available",
                entity=prod.product_id, field_name="detail",
                text=f"{g.rstrip()}\n{build_rich_deposit_detail(prod)}".strip(),
                source="snapshot",
                extras={"intent_id": "TERM_DEPOSIT_DETAIL_READ"},
            )]
        if prod is not None and task.object == "loan":
            loan = None
            if getattr(snapshot, "loans", None):
                loan = next((ln for ln in snapshot.loans if ln.product_id == prod.product_id), None)
            return [TaskEvidence(
                task_id=f"{task.id}.detail", domain="personal", status="available",
                entity=prod.product_id, field_name="detail",
                text=f"{g.rstrip()}\n{build_rich_loan_detail(prod, loan)}".strip(),
                source="snapshot",
                extras={"intent_id": "LOAN_DETAIL_READ"},
            )]
        if prod is not None and task.object == "account":
            from genesis_cognitive.context.response_formatting import format_money
            ccy = prod.currency or "DOP"
            bits = [f"**{display_label(prod)}**"]
            if prod.ledger_balance is not None:
                bits.append(f"saldo actual {format_money(prod.ledger_balance, ccy)}")
            if prod.available_balance is not None:
                bits.append(f"disponible {format_money(prod.available_balance, ccy)}")
            return [TaskEvidence(
                task_id=f"{task.id}.detail", domain="personal", status="available",
                entity=prod.product_id, field_name="detail",
                text=f"{g}" + " · ".join(bits) + ".",
                source="snapshot",
                extras={"intent_id": "ACCOUNT_BALANCE_READ"},
            )]

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

    # Pagos próximos transversales (P12)
    if (task.filters or {}).get("upcoming_payments"):
        from genesis_cognitive.router.field_guardrails import apply_upcoming_payments_guardrail
        up = apply_upcoming_payments_guardrail(snapshot, question or "")
        if up is None:
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="absent",
                field_name="due_date",
                text="No encontré pagos próximos en tu portafolio.",
                source="upcoming_payments",
            )]
        _st, _acts, txt, _sug = up
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="available",
            field_name="due_date",
            text=txt or "",
            source="upcoming_payments",
        )]

    # Comparar tarjetas: mayor disponible (P09)
    if (
        task.object == "credit_card"
        and task.action == "compare"
        and (task.filters or {}).get("operator") == "max"
    ):
        cards = [
            p for p in snapshot.products
            if p.product_type == "CREDIT_CARD" and str(p.status).lower() == "active"
        ]
        if not cards:
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="absent",
                field_name="available",
                text="No tienes tarjetas de crédito activas para comparar.",
                source="snapshot",
            )]

        def _avail(c: Any) -> float:
            raw = (
                c.available_purchases_domestic
                if c.available_purchases_domestic is not None
                else c.available_balance
            )
            try:
                return float(raw or 0)
            except (TypeError, ValueError):
                return 0.0

        best = max(cards, key=_avail)
        from genesis_cognitive.context.product_display import display_label_in_context
        from genesis_cognitive.context.response_formatting import format_money
        label = display_label_in_context(best, cards)
        val = format_money(
            best.available_purchases_domestic
            if best.available_purchases_domestic is not None
            else best.available_balance,
            best.currency or "DOP",
        )
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="available",
            entity=best.product_id, field_name="available", value=val,
            text=f"La tarjeta con más crédito disponible es **{label}** (**{val}**).",
            source="snapshot",
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
            from genesis_cognitive.context.product_display import display_label_in_context
            first_label = display_label_in_context(first, daps)
            return [TaskEvidence(
                task_id=task.id, domain="personal", status="available",
                entity=first.product_id, field_name="maturity", value=first.maturity_date,
                text=(
                    f"Entre los certificados con fecha válida, el que vence primero es "
                    f"**{first_label}** (vencimiento **{first.maturity_date}**)."
                    + warn
                ),
                source="snapshot",
            )]
        from genesis_cognitive.context.product_display import display_label_in_context
        lines: list[str] = []
        for p in daps:
            label = display_label_in_context(p, daps)
            bits: list[str] = [label]
            if "rate" in fields and p.interest_rate is not None:
                bits.append(f"tasa {p.interest_rate}%")
            if "maturity" in fields and p.maturity_date:
                bits.append(f"vence {p.maturity_date}")
            if (
                ("principal" in fields or "balance" in fields or "capital" in fields)
                and "balance" not in excl
                and "capital" not in excl
                and "principal" not in excl
            ):
                capital = p.ledger_balance if p.ledger_balance is not None else p.available_balance
                if capital is not None:
                    bits.append(f"balance {_money(capital, p.currency or 'DOP')}")
            lines.append(" — ".join(bits))
        body = "Tus certificados:\n" + "\n".join(f"• {ln}" for ln in lines)
        # Guardrail: no mencionar tarjetas
        low = body.lower()
        assert "tarjeta" not in low
        return [TaskEvidence(
            task_id=task.id, domain="personal", status="available",
            field_name="+".join(fields), text=body, source="snapshot",
            extras={"excluded": list(excl), "count": len(daps), "cardinality": "all"},
        )]

    # Una evidencia por campo (P01 multi-campo)
    # cardinality=all en tarjeta: un solo resumen (evita duplicar por cada field)
    if (
        task.object == "credit_card"
        and task.cardinality == "all"
        and task.action == "read_field"
        and not task.entity_ref
    ):
        fields_set = set(fields or [])
        if fields_set == {"balance"}:
            summary_field = "balance"
        elif fields_set == {"available"}:
            summary_field = "available"
        else:
            summary_field = "multi_summary"
        # Si el plan acotó TC concretas (compare personal), resumir solo esas
        cand = list((task.filters or {}).get("candidate_ids") or [])
        if cand and snapshot is not None:
            by_id = {str(p.product_id): p for p in snapshot.products}
            scoped = [by_id[i] for i in cand if i in by_id]
            if len(scoped) >= 2:
                from genesis_cognitive.context.product_display import display_label_in_context
                from genesis_cognitive.context.response_formatting import format_money

                lines = ["Aquí tienes la comparación entre tus tarjetas de crédito:", ""]
                for c in scoped:
                    label = display_label_in_context(c, scoped)
                    bal = (
                        c.ledger_balance
                        if c.ledger_balance is not None
                        else c.domestic_currency_balance
                    )
                    avail = (
                        c.available_purchases_domestic
                        if c.available_purchases_domestic is not None
                        else c.available_balance
                    )
                    cur = c.currency or "DOP"
                    lines.append(f"### {label}")
                    if bal is not None:
                        lines.append(f"- Saldo pendiente: {format_money(bal, cur)}")
                    if avail is not None:
                        lines.append(f"- Límite disponible: {format_money(avail, cur)}")
                    lines.append("")
                return [TaskEvidence(
                    task_id=f"{task.id}.all",
                    domain="personal",
                    status="available",
                    field_name="multi_summary",
                    text="\n".join(lines).strip(),
                    source="snapshot",
                    extras={
                        "cardinality": "all",
                        "candidate_ids": cand,
                        "compare_personal_cards": True,
                    },
                )]
        pkt = IntentPacket(
            "personal",
            "credit_card",
            summary_field,
            scope="all",
            confidence=0.95,
            rewritten_question=question,
            source="plan_executor",
            rationale=f"plan:{task.id}:all",
        )
        result = execute_grounded(pkt, snapshot, question=question, session=session)
        st = "available"
        if result.status == "CLARIFICATION_REQUIRED":
            st = "needs_clarification"
        elif result.status in ("UNSUPPORTED", "NON_OPERATIONAL"):
            st = "unsupported"
        elif not (result.text or "").strip():
            st = "absent"
        return [TaskEvidence(
            task_id=f"{task.id}.all",
            domain="personal",
            status=st,
            entity=result.account_ref or task.entity_ref,
            field_name="multi_summary",
            text=result.text or "",
            source="grounded",
            extras={"intent_id": result.intent_id, "status": result.status, "cardinality": "all"},
        )]

    clarified_once = False
    for fld in fields:
        scope = "all" if task.cardinality == "all" else "single"
        # Pregunta sintética para no dejar que continuity reescriba el campo
        # a partir del texto de selección ordinal («el segundo»).
        synth_q = {
            "rate": "¿cuál es la tasa?",
            "available": "¿cuánto tengo disponible?",
            "balance": (
                "¿cuál es el saldo contable?"
                if "contable" in (question or "").lower()
                else ("¿cuánto debo?" if task.object == "credit_card" else "¿cuál es el saldo actual?")
            ),
            "due_date": "¿cuál es la fecha de pago?",
            "principal": (
                "¿cuánto invertí?"
                if task.object == "term_deposit"
                else "¿cuál es el capital pendiente?"
            ),
            "interest_amount": "¿cuánto ha generado?",
            "maturity": "¿cuál es el vencimiento?",
            "installment_amount": "¿cuánto es la próxima cuota?",
            "min_payment": "¿cuál es el pago mínimo?",
            "payoff": "¿cuál es el total adeudado?",
            "detail": "¿cuál es el detalle de este producto?",
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
            # Una sola clarificación por tarea multi-campo (evita duplicar el texto)
            if clarified_once:
                continue
            clarified_once = True
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
            extras={
                "intent_id": result.intent_id,
                "status": result.status,
                **{
                    k: v for k, v in (result.trace or {}).items()
                    if k in (
                        "field_path", "field_meaning", "field_origin",
                        "source_fetched_at", "payoff_accredited", "payoff_limitation",
                        "payment_window_reference_date", "payment_window_timezone",
                        "payment_window_days", "payment_window_end_date",
                        "payment_classifications",
                    )
                },
            },
        ))
        if st == "needs_clarification":
            # No seguir pidiendo campos hasta resolver el producto
            break
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
        if task.action == "count":
            evidences.append(_execute_count(task, snapshot))
            continue
        if task.domain == "institutional":
            ev = _execute_institutional(task, snapshot, session, question=question)
            evidences.append(ev)
            knowledge_topic = (ev.field_name or "institutional")[:120]
            # Excursión institucional: no borrar pendiente personal
            if session is not None and getattr(session, "pending_action", None) is not None:
                preserve_pending = True
            continue
        if task.domain in ("catalog", "process"):
            ev = _execute_catalog_or_process(
                task, snapshot, session, question=question,
            )
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
            answered_all = (
                task.cardinality in ("all", "compare")
                or task.action == "compare"
                or any(e.extras.get("cardinality") == "all" for e in evs)
            )
            for ev in evs:
                if ev.status == "needs_clarification":
                    pending_out = pending_out or []
                    display_order: list[str] = list((task.filters or {}).get("candidate_ids") or [])
                    if not display_order and snapshot is not None and task.object == "credit_card":
                        display_order = [
                            p.product_id for p in snapshot.products
                            if p.product_type == "CREDIT_CARD"
                            and str(p.status).lower() == "active"
                        ]
                    elif not display_order and snapshot is not None and task.object == "loan":
                        display_order = [
                            p.product_id for p in snapshot.products
                            if p.product_type == "LOAN"
                            and str(p.status).lower() == "active"
                        ]
                    elif not display_order and snapshot is not None and task.object == "term_deposit":
                        display_order = [
                            p.product_id for p in snapshot.products
                            if p.product_type == "TERM_DEPOSIT"
                            and str(p.status).lower() == "active"
                        ]
                    elif not display_order and snapshot is not None and task.object == "product":
                        display_order = [
                            p.product_id for p in snapshot.products
                            if str(p.status).lower() == "active"
                        ]
                    pending_out.append({
                        "task_id": task.id,
                        "object": task.object,
                        "fields": list(task.fields or []),
                        "original_question": question,
                        "display_order": display_order,
                    })
                if answered_all:
                    clear_pending = True
                    continue
                if ev.status == "available" and ev.entity and task.object == "credit_card":
                    focus_out = ("CARD", ev.entity, "CREDIT_CARD_DETAIL_READ")
                    # Primera respuesta con foco: ofrecer el resto de tarjetas
                    multi_pending = _preserve_multi_product_pending(
                        session, task.object, exclude_entity=ev.entity,
                    )
                    if not multi_pending and snapshot is not None and task.cardinality != "all":
                        others = [
                            p.product_id for p in snapshot.products
                            if p.product_type == "CREDIT_CARD"
                            and str(p.status).lower() == "active"
                        ]
                        if len(others) > 1:
                            multi_pending = [{
                                "task_id": task.id,
                                "object": "credit_card",
                                "fields": list(task.fields or []),
                                "original_question": question,
                                "display_order": others,
                                "last_answered_entity": ev.entity,
                            }]
                    if multi_pending:
                        pending_out = pending_out or multi_pending
                        clear_pending = False
                    else:
                        clear_pending = True
                elif ev.status == "available" and ev.entity and task.object == "account":
                    focus_out = ("ACCOUNT", ev.entity, "ACCOUNT_BALANCE_READ")
                    clear_pending = True
                elif ev.status == "available" and ev.entity and task.object == "loan":
                    focus_out = ("LOAN", ev.entity, "LOAN_DETAIL_READ")
                    multi_pending = _preserve_multi_product_pending(
                        session, task.object, exclude_entity=ev.entity,
                    )
                    if not multi_pending and snapshot is not None and task.cardinality != "all":
                        # Conservar solo el mismo subconjunto (p. ej. personales), no hipotecario
                        cand = list((task.filters or {}).get("candidate_ids") or [])
                        role = str((task.filters or {}).get("loan_role") or "")
                        others = cand[:] if cand else [
                            p.product_id for p in snapshot.products
                            if p.product_type == "LOAN"
                            and str(p.status).lower() == "active"
                        ]
                        if role and snapshot is not None and not cand:
                            filtered = []
                            for p in snapshot.products:
                                if p.product_type != "LOAN" or str(p.status).lower() != "active":
                                    continue
                                alias = (getattr(p, "alias", "") or "").lower()
                                if role == "personal" and "personal" in alias:
                                    filtered.append(p.product_id)
                                elif role == "mortgage" and "hipotec" in alias:
                                    filtered.append(p.product_id)
                            if filtered:
                                others = filtered
                        if len(others) > 1:
                            multi_pending = [{
                                "task_id": task.id,
                                "object": "loan",
                                "fields": list(task.fields or []),
                                "original_question": question,
                                "display_order": others,
                                "last_answered_entity": ev.entity,
                            }]
                    if multi_pending:
                        pending_out = pending_out or multi_pending
                        clear_pending = False
                    else:
                        clear_pending = True
                elif ev.status == "available" and ev.entity and task.object == "term_deposit":
                    focus_out = ("TERM_DEPOSIT", ev.entity, "TERM_DEPOSIT_DETAIL_READ")
                    multi_pending = _preserve_multi_product_pending(
                        session, task.object, exclude_entity=ev.entity,
                    )
                    if multi_pending:
                        pending_out = pending_out or multi_pending
                        clear_pending = False
                    else:
                        clear_pending = True
            continue
        # chitchat / none
        evidences.append(TaskEvidence(
            task_id=task.id, domain=task.domain, status="available",
            text="", source="noop",
        ))

    # Componer texto: toda tarea visible (sin duplicados)
    evidences = _dedupe_evidence_texts(evidences)
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
    has_data = any(e.status in ("available", "partial") and e.text for e in evidences)
    has_clarify = any(e.status == "needs_clarification" for e in evidences)
    if has_data and has_clarify:
        overall = "VALID_CONTRACT"  # responde lo sustentado y aclara lo pendiente en el mismo texto
        intent = "TURN_PLAN_PARTIAL"

    text = _compose_multi_field_bullets(evidences, snapshot)
    if text:
        seen_norm = {_normalize_evidence_text(text)}
        extras: list[str] = []
        for ev in evidences:
            raw = (ev.text or "").strip()
            if not raw:
                continue
            nrm = _normalize_evidence_text(raw)
            if nrm in seen_norm:
                continue
            if any(nrm in prev or prev in nrm for prev in seen_norm if len(nrm) > 50 and len(prev) > 50):
                continue
            # Anexar resúmenes all / unsupported / compare que el pliegue no cubrió
            if (
                ev.field_name == "multi_summary"
                or ev.status == "unsupported"
                or ev.extras.get("cardinality") == "all"
                or (ev.field_name == "maturity" and "vence primero" in nrm)
            ):
                extras.append(raw)
                seen_norm.add(nrm)
        if extras:
            text = text + "\n\n" + "\n\n".join(extras)
    else:
        text = "\n\n".join(blocks).strip()
    if not text:
        text = _contact_channels_reply(
            "No pude completar la consulta con la información disponible."
        )
        overall = "VALID_CONTRACT"

    # Familias distintas en la misma respuesta → solo texto (sin cards)
    personal_objects = set()
    for task in plan.tasks:
        if task.domain == "personal" and task.object in (
            "credit_card", "loan", "account", "term_deposit",
        ):
            personal_objects.add(task.object)
    has_clarify = any(e.status == "needs_clarification" for e in evidences)
    multi_family = len(personal_objects) > 1
    answered_all_family = any(
        t.cardinality in ("all", "compare") or t.action == "compare"
        for t in plan.tasks
        if t.domain == "personal"
    )
    multi_loan_answered = len({
        t.entity_ref for t in plan.tasks
        if t.object == "loan" and t.entity_ref
    }) >= 2
    # Mostrar cards si hay aclaración pendiente (p. ej. ahorros OK + ¿cuál tarjeta?).
    # Suprimir solo cuando ya se listó todo o hay varias familias resueltas sin aclarar.
    suppress_options = (
        (answered_all_family and not has_clarify)
        or (multi_loan_answered and not has_clarify)
        or (multi_family and not has_clarify and not pending_out)
    )

    # Opciones de desambiguación desde pendientes (sin el producto ya respondido)
    options_out: list[dict] | None = None
    if pending_out and snapshot is not None and (has_clarify or not suppress_options):
        from genesis_cognitive.context.app_channel import build_product_options
        # Fusionar pendientes del mismo objeto (p. ej. rate+maturity en dos tasks)
        merged: dict[str, dict] = {}
        for pt in pending_out:
            obj = str(pt.get("object") or "")
            key = obj or str(pt.get("task_id") or id(pt))
            if key not in merged:
                merged[key] = dict(pt)
                merged[key]["fields"] = list(pt.get("fields") or [])
                merged[key]["display_order"] = list(pt.get("display_order") or [])
            else:
                for f in pt.get("fields") or []:
                    if f not in merged[key]["fields"]:
                        merged[key]["fields"].append(f)
                if not merged[key]["display_order"] and pt.get("display_order"):
                    merged[key]["display_order"] = list(pt.get("display_order") or [])
                if not merged[key].get("original_question") and pt.get("original_question"):
                    merged[key]["original_question"] = pt.get("original_question")
        # Con aclaración: emitir cards de la familia pendiente (aunque haya otras respondidas)
        clarify_objs = {
            str(pt.get("object") or "")
            for pt in pending_out
            if pt.get("display_order")
        }
        for pt in merged.values():
            obj = str(pt.get("object") or "")
            if has_clarify and clarify_objs and obj not in clarify_objs:
                continue
            order = [
                pid for pid in (pt.get("display_order") or [])
                if not account_ref or str(pid) != str(account_ref)
            ]
            if not order:
                continue
            by_id = {p.product_id: p for p in snapshot.products}
            pool = [by_id[i] for i in order if i in by_id]
            if pool:
                orig_q = str(pt.get("original_question") or question or "")
                options_out = build_product_options(
                    pool,
                    fields=list(pt.get("fields") or []),
                    question=orig_q,
                    snapshot=snapshot,
                    allow_single=True,
                ) or None
                break
    elif suppress_options and not has_clarify:
        options_out = None
        if multi_family or multi_loan_answered:
            pending_out = None
            clear_pending = True

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

    field_accreditation: dict[str, Any] = {}
    payment_window_audit: dict[str, Any] = {}
    for e in evidences:
        acc = {
            k: e.extras.get(k)
            for k in (
                "field_path", "field_meaning", "field_origin",
                "source_fetched_at", "payoff_accredited", "payoff_limitation",
            )
            if e.extras.get(k) is not None
        }
        if acc:
            field_accreditation[e.task_id] = acc
        for wk in (
            "payment_window_reference_date", "payment_window_timezone",
            "payment_window_days", "payment_window_end_date",
            "payment_classifications",
        ):
            if e.extras.get(wk) is not None:
                payment_window_audit[wk] = e.extras.get(wk)

    return PlanExecutionResult(
        status=overall,
        text=text,
        intent_id=intent,
        evidences=evidences,
        actions=actions,
        account_ref=account_ref,
        options=options_out,
        route="knowledge" if all(e.domain in ("institutional", "catalog", "process") for e in evidences) else "personal",
        trace={
            "plan": plan.to_dict(),
            "task_count": len(plan.tasks),
            "task_statuses": {e.task_id: e.status for e in evidences},
            "evidence_sources": sorted({e.source for e in evidences if e.source}),
            "interpreter": plan.source,
            "transition": plan.transition,
            "field_accreditation": field_accreditation or None,
            "payment_window": payment_window_audit or None,
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
