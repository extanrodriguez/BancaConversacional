"""FAQ guardrail — respuestas de información general desde Base de Conocimiento Excel."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


# Señales institucionales: permiten match con frases cortas (ej. "Mision")
_INSTITUTIONAL_KEYWORDS = frozenset(
    {
        "mision",
        "misión",
        "vision",
        "visión",
        "valores",
        "banco",
        "bsc",
        "institucion",
        "institución",
        "empresa",
        "santa",
        "cruz",
    }
)

_DEFINITION_MARKERS = (
    "qué es",
    "que es",
    "qué significa",
    "que significa",
    "significa",
    "definición",
    "definicion",
    "explícame",
    "explicame",
    "cuéntame sobre",
    "cuentame sobre",
    "háblame de",
    "hablame de",
    "háblame sobre",
    "hablame sobre",
    "información sobre",
    "informacion sobre",
    "cómo funciona",
    "como funciona",
)

_PERSONAL_FIELD_MARKERS = (
    "disponible",
    "saldo",
    "balance",
    "tasa",
    "cuota",
    "corte",
    "corta",
    "limite",
    "límite",
    "capital",
    "mora",
    "vencimiento",
    "adeud",
    "debo",
    "cuanto tengo",
    "cuánto tengo",
    "cuanto me queda",
    "cuánto me queda",
)

_DEICTIC_PRODUCT_REFS = (
    "esa cuenta",
    "esa tarjeta",
    "ese prestamo",
    "ese préstamo",
    "ese producto",
    "esa misma",
    "el mismo",
    "la misma",
    "de esa cuenta",
    "de esa tarjeta",
    "la de dolares",
    "la de dólares",
    "la de pesos",
    "la de usd",
    "el de dolares",
    "el de dólares",
    "el de pesos",
)

_STOP_CONCEPT = frozenset(
    {
        "que", "qué", "es", "la", "el", "los", "las", "de", "del", "un", "una",
        "significa", "definicion", "definición", "explicame", "explícame",
        "sobre", "dime", "dame", "cual", "cuál", "como", "cómo", "funciona",
        "informacion", "información", "me", "mi", "mis",
    }
)

def _is_explicit_knowledge_definition(text: str) -> bool:
    ql = (text or "").lower()
    return any(s in ql for s in _DEFINITION_MARKERS)


def _has_deictic_product_ref(text: str) -> bool:
    ql = (text or "").lower()
    return any(s in ql for s in _DEICTIC_PRODUCT_REFS)


def _pending_awaits_product(session: Any | None) -> bool:
    if session is None:
        return False
    pending = getattr(session, "pending_action", None)
    if pending is None:
        return False
    missing = getattr(pending, "missing_requirements", None) or []
    return "account_ref" in missing


def _has_personal_field_ask(text: str) -> bool:
    """Pide un dato de portafolio (campo), no una definición."""
    ql = (text or "").lower()
    if not any(s in ql for s in _PERSONAL_FIELD_MARKERS):
        return False
    if _is_explicit_knowledge_definition(ql):
        return False
    ask_shape = any(
        s in ql
        for s in (
            "mi ",
            "mis ",
            "mío",
            "mía",
            "cual es",
            "cuál es",
            "cuanto",
            "cuánto",
            "dime",
            "dame",
            "quiero",
            "necesito",
            "consulta",
            "revisa",
            "y el ",
            "y la ",
            "el de ",
            "la de ",
            "cuando corta",
            "cuándo corta",
            "cuando vence",
            "cuándo vence",
        )
    )
    return ask_shape or _has_deictic_product_ref(ql)


def is_personal_portfolio_faq_blocked(
    text: str,
    *,
    session: Any | None = None,
    snapshot: Any | None = None,
) -> bool:
    """True si el FAQ no debe consumir la pregunta (dato personal / continuidad).

    No se basa solo en posesivos: usa campo solicitado, pending, deíxis y foco.
    Las definiciones explícitas NO se bloquean aquí.
    """
    ql = (text or "").lower().strip()
    if not ql:
        return False
    if _is_explicit_knowledge_definition(ql):
        return False
    # Misión/visión/valores cortas: siempre elegibles para FAQ (aunque haya pending)
    if _is_institutional_short(ql):
        return False

    if _pending_awaits_product(session):
        # Selección / follow-up de clarificación de producto → no glosario
        return True

    if _has_deictic_product_ref(ql) and any(s in ql for s in _PERSONAL_FIELD_MARKERS):
        return True

    if _has_personal_field_ask(ql):
        return True

    # Foco de sesión + campo personal corto ("y la tasa?", "el disponible?")
    focus = getattr(session, "product_focus", None) if session is not None else None
    last = getattr(session, "last_resolved", None) if session is not None else None
    has_focus = bool(
        (focus is not None and getattr(focus, "product_id", None))
        or (last is not None and getattr(last, "account_ref", None))
    )
    if has_focus and any(s in ql for s in _PERSONAL_FIELD_MARKERS) and len(ql) < 80:
        if not _is_explicit_knowledge_definition(ql):
            return True

    # Portafolio con productos que responden el campo y la pregunta es personal
    if snapshot is not None and _has_personal_field_ask(ql):
        return True

    return False


def is_mixed_personal_and_knowledge_question(text: str) -> bool:
    """Personal + definición en el mismo mensaje → no dejar que FAQ se quede solo."""
    ql = (text or "").lower()
    has_def = _is_explicit_knowledge_definition(ql) or any(
        s in ql
        for s in (
            "y qué significa",
            "y que significa",
            "y qué es",
            "y que es",
            "y su significado",
            "y el significado",
        )
    )
    if not has_def:
        return False
    personal_bit = any(
        s in ql
        for s in (
            "mi saldo",
            "mis saldos",
            "mi disponible",
            "cuanto tengo",
            "cuánto tengo",
            "mi tasa",
            "mi cuota",
            "mi tarjeta",
            "mi cuenta",
            "mi prestamo",
            "mi préstamo",
            "tasa de mi",
            "cuota de mi",
            "dime mi",
            "dame mi",
        )
    ) or _has_deictic_product_ref(ql)
    return personal_bit


def _concept_tokens_from_definition_question(text: str) -> set[str]:
    ql = (text or "").lower()
    markers = (
        "qué significa",
        "que significa",
        "qué son",
        "que son",
        "qué es",
        "que es",
        "definición de",
        "definicion de",
        "explícame",
        "explicame",
        "cuéntame sobre",
        "cuentame sobre",
        "háblame de",
        "hablame de",
        "información sobre",
        "informacion sobre",
    )
    # Preguntas compuestas («qué son A y qué es B»): unir conceptos de cada cláusula.
    parts: list[str] = []
    remaining = ql
    found = False
    for marker in markers:
        if marker in remaining:
            found = True
            chunks = remaining.split(marker)
            remaining = chunks[0]
            for chunk in chunks[1:]:
                # Cortar en el siguiente marcador o conector de contraste
                piece = chunk
                for m2 in markers:
                    if m2 in piece:
                        piece = piece.split(m2, 1)[0]
                for stop in (" y que ", " y qué ", "?", ".", ";"):
                    if stop in piece:
                        piece = piece.split(stop, 1)[0]
                parts.append(piece)
    if not found:
        parts = [ql]
    out: set[str] = set()
    for part in parts:
        out |= {t for t in _tokens(part) if t not in _STOP_CONCEPT and len(t) > 2}
    return out


def _definition_hit_is_relevant(question: str, hit: dict[str, Any] | None) -> bool:
    """Evita devolver topics ajenos (ej. 'Cargo') ante 'qué significa saldo disponible'."""
    if not hit:
        return False
    if not _is_explicit_knowledge_definition(question):
        return True
    answer = str(hit.get("answer") or "")
    topic = str(hit.get("topic") or "")
    # Respuestas de matriz de prueba / saldo personal simulado ≠ definición
    ans_l = answer.lower()
    topic_l = topic.lower()
    if re.search(r"fila\s+\d+", topic_l) or "respuesta / contexto aprobado" in ans_l:
        return False
    if re.search(r"(tienes|tu)\s+rd\$|terminada en\s+\d{3,}", ans_l) and (
        "significa" in _norm(question) or "definicion" in _norm(question) or "qué es" in question.lower()
    ):
        return False
    concept = _concept_tokens_from_definition_question(question)
    if not concept:
        return True
    blob = _norm(
        f"{hit.get('topic') or ''} {(hit.get('answer') or '')[:320]}"
    )
    blob_tokens = _tokens(blob)
    # Al menos un token del concepto debe aparecer en topic/respuesta
    if concept & blob_tokens:
        return True
    # También aceptar si el topic contiene la frase del concepto
    concept_phrase = " ".join(sorted(concept))
    topic_n = _norm(str(hit.get("topic") or ""))
    if any(tok in topic_n for tok in concept):
        return True
    # FAQ lexical fuerte cuyo topic aparece en la pregunta completa
    # (p.ej. «Puntos Santa Cruz» en pregunta que también pide cashback).
    q_tokens = _tokens(question)
    topic_tokens = _tokens(topic)
    score = float(hit.get("score") or 0)
    if score >= 0.78 and (topic_tokens & q_tokens):
        return True
    # rechazo: sin solape
    _ = concept_phrase
    return False


# Boost por topic cuando el usuario usa keyword corta / coloquial
_TOPIC_KEYWORD_BOOST: dict[str, tuple[str, ...]] = {
    "mision": ("mision", "misión", "proposito", "propósito"),
    "vision": ("vision", "visión"),
    "banco santa cruz": (
        "que es banco",
        "qué es banco",
        "que es bsc",
        "qué es bsc",
        "hablame del banco",
        "háblame del banco",
        "cuentame del banco",
        "cuéntame del banco",
        "sobre el banco",
        "informacion del banco",
        "información del banco",
    ),
}


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    t = t.replace("¿", "").replace("?", "").replace("¡", "").replace("!", "")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _tokens(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) > 2}


def _default_faq_path() -> str:
    env = os.getenv("GENESIS_FAQ_PATH", "").strip()
    if env:
        return env
    # Contenedor: /app/data/... ; local: repo/data/...
    root = Path(__file__).resolve().parents[3]
    return str(root / "data" / "kb_faq_vf01.json")


@lru_cache(maxsize=4)
def load_faq_entries(path: str) -> tuple[dict[str, Any], ...]:
    p = Path(path)
    if not p.is_file():
        return tuple()
    data = json.loads(p.read_text(encoding="utf-8"))
    entries = list(data.get("entries") or [])

    # Overlay Fase 1: ampliar expresiones / entradas institucionales sin reimportar Excel
    overlay = os.getenv("GENESIS_FAQ_OVERLAY_PATH", "").strip()
    if not overlay:
        overlay = str(Path(path).with_name("kb_faq_overlay_fase1.json"))
    op = Path(overlay)
    if op.is_file():
        extra = json.loads(op.read_text(encoding="utf-8"))
        by_id = {e.get("id"): e for e in entries if e.get("id")}
        for e in extra.get("entries") or []:
            eid = e.get("id")
            if eid and eid in by_id:
                merged = dict(by_id[eid])
                exprs = list(dict.fromkeys((merged.get("expressions") or []) + (e.get("expressions") or [])))
                merged["expressions"] = exprs
                if e.get("answer"):
                    merged["answer"] = e["answer"]
                if e.get("synonyms"):
                    merged["synonyms"] = e["synonyms"]
                by_id[eid] = merged
            else:
                entries.append(e)
                if eid:
                    by_id[eid] = e
        # rebuild preserving order + updates
        seen = set()
        rebuilt: list[dict[str, Any]] = []
        for e in entries:
            eid = e.get("id")
            if eid and eid in by_id:
                if eid in seen:
                    continue
                rebuilt.append(by_id[eid])
                seen.add(eid)
            elif not eid:
                rebuilt.append(e)
        # append overlay-only ids already in by_id not in rebuilt
        for eid, e in by_id.items():
            if eid not in seen:
                rebuilt.append(e)
                seen.add(eid)
        entries = rebuilt

    # Overlay Potenciación Lunes (cuerpo completo + procedimientos QA)
    pot = os.getenv("GENESIS_FAQ_POTENCIACION_OVERLAY_PATH", "").strip()
    if not pot:
        pot = str(Path(path).with_name("kb_faq_overlay_potenciacion_lunes.json"))
    pp = Path(pot)
    if pp.is_file():
        extra = json.loads(pp.read_text(encoding="utf-8"))
        by_id = {e.get("id"): dict(e) for e in entries if e.get("id")}
        order: list[str] = [e.get("id") for e in entries if e.get("id")]
        for e in extra.get("entries") or []:
            eid = e.get("id")
            if not eid:
                continue
            if eid in by_id:
                merged = dict(by_id[eid])
                exprs = list(dict.fromkeys(
                    (merged.get("expressions") or []) + (e.get("expressions") or [])
                ))
                merged["expressions"] = exprs
                # Preferir cuerpo más completo (Criterio de aceptación origen)
                new_ans = (e.get("answer") or "").strip()
                old_ans = (merged.get("answer") or "").strip()
                if new_ans and (not old_ans or len(new_ans) > len(old_ans) + 40):
                    merged["answer"] = new_ans
                if e.get("content_kind"):
                    merged["content_kind"] = e["content_kind"]
                if e.get("synonyms"):
                    merged["synonyms"] = list(dict.fromkeys(
                        (merged.get("synonyms") or []) + (e.get("synonyms") or [])
                    ))
                by_id[eid] = merged
            else:
                by_id[eid] = dict(e)
                order.append(eid)
        entries = [by_id[i] for i in order if i in by_id]

    return tuple(entries)


def clear_faq_cache() -> None:
    load_faq_entries.cache_clear()


def _keyword_boost(question: str, entry: dict[str, Any]) -> float:
    qn = _norm(question)
    topic = _norm(entry.get("topic") or "")
    boost = 0.0

    # Sinónimos explícitos en entry (deben aparecer en la pregunta)
    for syn in entry.get("synonyms") or []:
        sn = _norm(syn)
        if not sn or len(sn) < 3:
            continue
        if qn == sn:
            boost = max(boost, 0.95)
        elif sn in qn:
            # Evitar falsos positivos tipo "mision" ⊂ palabras ajenas: token completo
            if sn in qn.split() or f" {sn} " in f" {qn} ":
                boost = max(boost, 0.88)

    for topic_key, keys in _TOPIC_KEYWORD_BOOST.items():
        if topic_key in topic or topic == topic_key:
            for k in keys:
                kn = _norm(k)
                if not kn:
                    continue
                if qn == kn:
                    boost = max(boost, 0.9)
                elif len(qn) <= 12 and (kn.startswith(qn) or qn.startswith(kn)):
                    # keyword corta del usuario: "Mision", "Vision"
                    boost = max(boost, 0.9)
                elif kn in qn and (kn in qn.split() or len(kn) >= 8):
                    boost = max(boost, 0.85)

    # Match exacto del topic corto ("mision") solo si el usuario lo dijo
    if topic and len(topic) >= 4:
        if qn == topic:
            boost = max(boost, 0.88)
        elif topic in qn.split() or f" {topic} " in f" {qn} ":
            boost = max(boost, 0.82)

    return boost


_DEF_PREFIX_RE = re.compile(
    r"^(?:¿?\s*)?(?:"
    r"(?:qué|que)\s+es(?:\s+una|\s+un|\s+la|\s+el)?"
    r"|(?:explícame|explicame|cuéntame|cuentame|háblame|hablame)(?:\s+(?:de|sobre))?"
    r"|(?:información|informacion)\s+sobre"
    r"|dime\s+(?:qué|que)\s+es(?:\s+una|\s+un|\s+la|\s+el)?"
    r")\s+",
    re.IGNORECASE,
)


def _strip_definitional_prefix(question: str) -> str | None:
    """'¿Qué es una Visa Platinum?' → 'Visa Platinum' para match FAQ."""
    t = (question or "").strip()
    if not t:
        return None
    m = _DEF_PREFIX_RE.match(t)
    if not m:
        return None
    core = t[m.end() :].strip(" ?.¡!¿")
    if not core or _norm(core) == _norm(t):
        return None
    return core


def _score(question: str, entry: dict[str, Any]) -> float:
    qn = _norm(question)
    q_tokens = _tokens(question)
    if not qn:
        return 0.0
    best = _keyword_boost(question, entry)
    gloss = {"que", "significa", "explicame", "dime", "hablame", "cuentame", "informacion", "sobre", "definicion"}
    for expr in entry.get("expressions") or []:
        en = _norm(expr)
        if not en:
            continue
        if qn == en:
            return 1.0
        if en in qn or qn in en:
            e_tokens = _tokens(expr)
            extra = q_tokens - e_tokens - gloss
            # "qué es tarjeta de crédito" ⊂ "qué es tarjeta de crédito Visa Clásica"
            # no debe ganar al topic específico
            if en in qn and len(extra) >= 2:
                best = max(best, 0.72)
            else:
                best = max(best, 0.92)
            continue
        e_tokens = _tokens(expr)
        if not e_tokens or not q_tokens:
            continue
        overlap = len(q_tokens & e_tokens) / max(len(e_tokens), 1)
        length_ratio = min(len(q_tokens), len(e_tokens)) / max(len(q_tokens), len(e_tokens))
        best = max(best, overlap * 0.85 + length_ratio * 0.1)
    topic = _norm(entry.get("topic") or "")
    kind = str(entry.get("content_kind") or "")
    # Evitar que el glosario «Cliente» gane a Visa Joven / procedimientos
    if topic in {"cliente", "clientes"} and "cliente" not in qn.split():
        best -= 0.55
    if kind in ("product_knowledge", "procedure", "scoped_editorial_summary"):
        best += 0.08
    if topic and len(topic) > 4 and topic in qn:
        specificity = min(len(topic) / max(len(qn), 1), 1.0)
        best = max(best, 0.82 + 0.14 * specificity)
    else:
        t_tokens = _tokens(topic) if topic else set()
        if t_tokens and q_tokens and len(t_tokens) >= 3:
            cov = len(q_tokens & t_tokens) / max(len(t_tokens), 1)
            if cov >= 0.75:
                best = max(best, 0.8 + 0.1 * cov)
    # Boost temas específicos de uso internacional / conversión
    if any(s in qn for s in ("conversion", "internacional", "fuera del pais", "fuera del país")):
        if any(s in topic for s in ("conversion", "internacional", "moneda")):
            best = max(best, 0.95)
    if any(s in qn for s in ("visa joven", "joven")) and "joven" in topic:
        best = max(best, 0.95)
    if any(s in qn for s in ("visa infinite", "infinite")) and "infinite" in topic:
        best = max(best, 0.95)
    # Crédito Diferido: no dejar que cancelación gane a la definición
    if any(s in qn for s in ("credito diferido", "crédito diferido", "multicredit")):
        if "diferido" in topic and "cancel" not in topic:
            best = max(best, 0.94)
        if "cancel" in topic and not any(s in qn for s in ("cancel", "baja", "dar de baja")):
            best = min(best, 0.45)
    return best


def _is_institutional_short(question: str) -> bool:
    qn = _norm(question)
    toks = qn.split()
    if not toks or len(toks) > 6:
        return False
    return any(_norm(k) in toks or _norm(k) in qn for k in _INSTITUTIONAL_KEYWORDS)


def _entry_usable(e: dict[str, Any]) -> bool:
    a = (e.get("answer") or "").strip().lower()
    if not a or len(a) < 40:
        return False
    if "basada exclusivamente en el contexto aprobado" in a:
        return False
    if "[respuesta" in a:
        return False
    if a.startswith("cuando no haya una intención") or a.startswith("cuando no haya una intencion"):
        return False
    if "la misma respuesta funcional" in a:
        return False
    # Filas meta de la matriz de pruebas (no son respuestas al cliente)
    if any(
        s in a
        for s in (
            "la ia cambia",
            "deja de utilizar el anterior",
            "cuando no haya una intencion",
            "cuando no haya una intención",
            "basada exclusivamente en el contexto aprobado",
            "el asistente debe",
            "validacion esperada",
            "validación esperada",
        )
    ):
        return False
    return True


def _asked_institutional_parts(question: str) -> list[str]:
    """Detecta misión/visión/valores pedidos en la misma pregunta (orden estable)."""
    qn = _norm(question)
    parts: list[str] = []
    if re.search(r"\bmision\b", qn):
        parts.append("mision")
    if re.search(r"\bvision\b", qn):
        parts.append("vision")
    if re.search(r"\bvalores\b", qn):
        parts.append("valores")
    return parts


def _find_entry_by_topic_key(entries: tuple[dict[str, Any], ...], key: str) -> dict[str, Any] | None:
    """Busca entrada institucional por topic/id conocido (misión, visión, valores)."""
    key_n = _norm(key)
    aliases = {
        "mision": ("mision", "misión", "vf01-r80"),
        "vision": ("vision", "visión", "vf01-r82"),
        "valores": ("valores", "vf01-r83", "vf01-valores"),
    }
    wanted = {_norm(a) for a in aliases.get(key_n, (key_n,))}
    for e in entries:
        if not _entry_usable(e):
            continue
        topic = _norm(e.get("topic") or "")
        eid = _norm(e.get("id") or "")
        if topic in wanted or eid in wanted:
            return e
        if topic.startswith(key_n) and len(topic) <= len(key_n) + 4:
            return e
    return None


def _combine_institutional_faq(
    question: str,
    entries: tuple[dict[str, Any], ...],
) -> dict[str, Any] | None:
    """Si piden misión y visión (y/o valores) juntas, fusiona respuestas del FAQ."""
    parts = _asked_institutional_parts(question)
    if len(parts) < 2:
        return None
    blocks: list[str] = []
    topics: list[str] = []
    ids: list[str] = []
    for part in parts:
        entry = _find_entry_by_topic_key(entries, part)
        if not entry or not entry.get("answer"):
            continue
        label = (entry.get("topic") or part).strip()
        ans = str(entry["answer"]).strip()
        # Evitar duplicar el título si la respuesta ya lo incluye
        if not ans.lower().startswith(label.lower()):
            blocks.append(f"**{label}**\n{ans}")
        else:
            blocks.append(ans)
        topics.append(label)
        if entry.get("id"):
            ids.append(str(entry["id"]))
    if len(blocks) < 2:
        return None
    return {
        "score": 0.97,
        "entry": None,
        "answer": "\n\n".join(blocks),
        "topic": " / ".join(topics),
        "id": "+".join(ids) if ids else "institutional-combo",
    }


def match_faq(question: str, *, faq_path: str | None = None, min_score: float = 0.78) -> dict[str, Any] | None:
    path = faq_path or _default_faq_path()
    entries = load_faq_entries(path)
    if not entries:
        return None

    # Preguntas compuestas institucionales: no devolver solo el primer topic
    combined = _combine_institutional_faq(question, entries)
    if combined:
        return combined

    qn0 = _norm(question)
    # Faceta dura: fallecidos / reclamaciones / Visa Joven no deben caer en «Cliente»
    if "fallec" in qn0 or "de cujus" in qn0 or "sucesor" in qn0:
        for e in entries:
            if not _entry_usable(e):
                continue
            topic = _norm(e.get("topic") or "")
            eid = str(e.get("id") or "")
            kind = str(e.get("content_kind") or "")
            if (
                "fallec" in topic
                or eid in ("vf01-r324", "bsc-fallecidos-orientacion")
                or (kind in ("procedure", "scoped_editorial_summary") and "fallec" in topic)
            ) and e.get("answer"):
                return {
                    "score": 0.99,
                    "entry": e,
                    "answer": e.get("answer"),
                    "topic": e.get("topic"),
                    "id": e.get("id"),
                }
    if "reclam" in qn0 and "cliente" not in qn0.split()[:2]:
        for e in entries:
            if not _entry_usable(e):
                continue
            topic = _norm(e.get("topic") or "")
            eid = str(e.get("id") or "")
            if (
                "reclam" in topic
                or eid in ("vf01-r320", "bsc-reclamaciones-orientacion", "fase1-proceso-reclamaciones")
            ) and e.get("answer") and len(str(e.get("answer") or "")) > 80:
                return {
                    "score": 0.99,
                    "entry": e,
                    "answer": e.get("answer"),
                    "topic": e.get("topic"),
                    "id": e.get("id"),
                }
    if "joven" in qn0 and any(s in qn0 for s in ("caracter", "que es", "qué es", "dirigida", "visa")):
        prefer_debit = "debito" in qn0 and "credito" not in qn0
        for e in entries:
            if not _entry_usable(e):
                continue
            topic = _norm(e.get("topic") or "")
            if "joven" not in topic:
                continue
            if prefer_debit and "debito" not in topic:
                continue
            if not prefer_debit and "debito" in topic and "credito" not in topic:
                continue
            if e.get("answer") and len(str(e.get("answer") or "")) > 40:
                return {
                    "score": 0.99,
                    "entry": e,
                    "answer": e.get("answer"),
                    "topic": e.get("topic"),
                    "id": e.get("id"),
                }
    # Platinum / Infinite / Gold: no permitir que otra Visa (p. ej. Joven) gane
    for product_key, topic_need in (
        ("platinum", "platinum"),
        ("platino", "platinum"),
        ("infinite", "infinite"),
        ("visa gold", "gold"),
        ("visa oro", "gold"),
    ):
        if product_key in qn0 and any(
            s in qn0 for s in ("caracter", "que es", "qué es", "requisito", "condicion", "visa", "compar")
        ):
            for e in entries:
                if not _entry_usable(e):
                    continue
                topic = _norm(e.get("topic") or "")
                ans_n = _norm(str(e.get("answer") or "")[:400])
                if topic_need not in topic and topic_need not in ans_n:
                    continue
                # Rechazar fichas de otro producto
                rivals = ("joven", "infinite", "platinum", "gold", "clasica", "classic", "empresarial")
                rival_hit = [
                    r for r in rivals
                    if r != topic_need and (r in topic or (r in ans_n and topic_need not in topic))
                ]
                if rival_hit and topic_need not in topic:
                    continue
                if e.get("answer") and len(str(e.get("answer") or "")) > 40:
                    return {
                        "score": 0.99,
                        "entry": e,
                        "answer": e.get("answer"),
                        "topic": e.get("topic"),
                        "id": e.get("id"),
                    }
            break
    # Multicrédito / Crédito diferido: preferir ficha de producto, no glosario adyacente
    if "multicredit" in qn0 or "credito diferido" in qn0:
        for e in entries:
            if not _entry_usable(e):
                continue
            topic = _norm(e.get("topic") or "")
            eid = str(e.get("id") or "")
            if eid in ("vf01-r102", "vf01-r089") or topic.startswith("multicredit") or (
                "multicredit" in topic and "modalidad" in topic
            ):
                if e.get("answer") and len(str(e.get("answer") or "")) > 40:
                    return {
                        "score": 0.99,
                        "entry": e,
                        "answer": e.get("answer"),
                        "topic": e.get("topic"),
                        "id": e.get("id"),
                    }
    if any(s in qn0 for s in ("cargo", "cargos")) and "tarjeta" in qn0:
        for e in entries:
            if not _entry_usable(e):
                continue
            topic = _norm(e.get("topic") or "")
            eid = str(e.get("id") or "")
            if eid == "vf01-r134" or topic in {"cargo", "cargos"} or topic.startswith("cargo"):
                if e.get("answer") and len(str(e.get("answer") or "")) > 40:
                    return {
                        "score": 0.99,
                        "entry": e,
                        "answer": e.get("answer"),
                        "topic": e.get("topic"),
                        "id": e.get("id"),
                    }
    if "cancel" in qn0 and any(s in qn0 for s in ("prestamo", "tarjeta", "credito diferido", "multicredit", "producto", "funciona", "proceso")):
        for e in entries:
            if not _entry_usable(e):
                continue
            topic = _norm(e.get("topic") or "")
            if "cancel" in topic and e.get("answer") and len(str(e.get("answer") or "")) > 80:
                return {
                    "score": 0.99,
                    "entry": e,
                    "answer": e.get("answer"),
                    "topic": e.get("topic"),
                    "id": e.get("id"),
                }

    # Umbral más permisivo para consultas institucionales cortas
    effective_min = min_score
    if _is_institutional_short(question):
        effective_min = min(min_score, float(os.getenv("GENESIS_FAQ_INSTITUTIONAL_MIN_SCORE", "0.65")))

    def _best(q_text: str) -> tuple[float, dict[str, Any]] | None:
        scored = [(_score(q_text, e), e) for e in entries if _entry_usable(e)]
        if not scored:
            return None
        q_toks = _tokens(q_text)

        def _topic_fit(e: dict[str, Any]) -> float:
            tt = _tokens(e.get("topic") or "")
            if not tt or not q_toks:
                return 0.0
            return (len(q_toks & tt) / max(len(tt), 1)) + 0.02 * len(tt)

        scored.sort(
            key=lambda x: (x[0], _topic_fit(x[1]), len(x[1].get("answer") or "")),
            reverse=True,
        )
        top_score, top = scored[0]
        if top_score < effective_min:
            return None
        if len(scored) > 1 and scored[1][0] >= effective_min and abs(scored[1][0] - top_score) < 0.08:
            if _norm(scored[1][1].get("topic") or "") != _norm(top.get("topic") or ""):
                tied = [e for s, e in scored if abs(s - top_score) < 0.08 and s >= effective_min]
                tied.sort(
                    key=lambda e: (_topic_fit(e), len(e.get("answer") or "")),
                    reverse=True,
                )
                top = tied[0]
        return top_score, top

    picked = _best(question)
    # "¿Qué es una Visa Platinum?" → reintentar con núcleo del producto
    if picked is None:
        core = _strip_definitional_prefix(question)
        if core:
            picked = _best(core)
    if picked is None:
        return None
    top_score, top = picked
    return {
        "score": top_score,
        "entry": top,
        "answer": top.get("answer"),
        "topic": top.get("topic"),
        "id": top.get("id"),
    }


def apply_faq_guardrail(
    snapshot: Any,
    raw_text: str,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Fast-path para preguntas de información general (misión, definiciones, etc.)."""
    q = (raw_text or "").strip()
    # Fase 1: permitir keywords institucionales cortas (>= 4); resto >= 8
    min_len = 4 if _is_institutional_short(q) else 8
    if len(q) < min_len:
        return None

    ql = q.lower()

    # Pregunta mixta (dato personal + definición): no consumir solo con FAQ
    if is_mixed_personal_and_knowledge_question(q):
        return None

    # Dato de portafolio / continuidad: no dejar que un match textual de FAQ gane
    if is_personal_portfolio_faq_blocked(q, session=session, snapshot=snapshot):
        return None

    # "dame más información" es follow-up de producto, no glosario de matriz KB
    if any(
        s in ql
        for s in (
            "mas informacion",
            "más información",
            "mas info",
            "más info",
            "dame mas",
            "dame más",
            "mas detalle",
            "más detalle",
        )
    ) and not any(
        s in ql
        for s in (
            "banco",
            "mision",
            "misión",
            "vision",
            "visión",
            "reclam",
            "fallecid",
            "contratar",
            "solicitar",
        )
    ):
        return None

    # Intent gate: dato del préstamo en foco de sesión → no glosario FAQ
    try:
        from genesis_cognitive.router.product_focus import prefer_personal_loan_over_knowledge
        from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question

        if prefer_personal_loan_over_knowledge(ql, session):
            return None
        if is_loan_field_question(ql):
            return None
    except Exception:
        pass

    # Fecha de pago personal (préstamo/tarjeta) ≠ definición FAQ "Fecha límite de pago"
    try:
        from genesis_cognitive.router.field_guardrails import is_personal_payment_date_question

        if is_personal_payment_date_question(ql):
            return None
    except Exception:
        pass

    # Selección por nombre comercial del portafolio (Visa Joven, Multicrédito…) ≠ FAQ banco
    # Pero definiciones ("qué es…") SÍ deben ir a FAQ aunque el alias coincida.
    _is_definition = any(
        s in ql
        for s in ("qué es", "que es", "significa", "definición", "definicion", "explícame", "explicame")
    )
    if snapshot is not None and not _is_definition:
        try:
            for p in getattr(snapshot, "products", ()) or ():
                alias = str(getattr(p, "alias", "") or "").strip().lower()
                if len(alias) >= 6 and alias in ql:
                    return None
                import re as _re

                toks = [
                    t
                    for t in _re.split(r"[^\wáéíóúñü]+", alias)
                    if len(t) >= 5 and t not in {"tarjeta", "credito", "crédito", "visa", "cuenta", "santa", "cruz", "banco"}
                ]
                if toks and all(t in ql for t in toks[-2:]):
                    return None
        except Exception:
            pass

    # Nombre de producto ambiguo → no FAQ (clarificación en field_guardrails)
    try:
        from genesis_cognitive.router.field_guardrails import is_ambiguous_product_noun_question

        if is_ambiguous_product_noun_question(ql):
            return None
    except Exception:
        pass

    personal = (
        "saldo", "balance", "cuenta", "tarjeta", "prestamo", "préstamo",
        "transfer", "movimiento", "cuota", "disponible", "limite", "límite",
        "certificado", "cdt", "deposito", "depósito",
    )
    knowledge_signals = (
        "que es", "qué es", "definicion", "definición", "significa",
        "mision", "misión", "vision", "visión",
        # No incluir "tasa" suelta: "cuál es mi tasa?" es personal, no glosario
        "requisito", "cargo", "comision", "comisión",
        "tasa de interes", "tasa de interés", "tarifario",
        "derecho", "deber", "pago minimo", "pago mínimo", "diferido",
        "como funciona", "cómo funciona", "cuales son", "cuáles son",
        "cuentame sobre", "cuéntame sobre", "hablame sobre", "háblame sobre",
        "hablame de", "háblame de", "cuentame de", "cuéntame de",
        "explicame", "explícame", "informacion sobre", "información sobre",
        "que diferencia", "qué diferencia", "diferencia", "diferencias",
        "caracteristicas", "características", "beneficios",
        "contratar", "puedo contratar", "puedo abrir", "productos de cuentas",
        "tipos de cuenta", "cuentas que ofrece", "en el banco", "con el banco",
        "tiene el banco", "ofrece el banco", "del banco",
        "reclamacion", "reclamación", "proceso de reclam",
        "fallecid", "fallecimiento", "retiro de fondos",
        "cancelo", "cancelar", "cancelacion", "cancelación",
        "como se usa", "cómo se usa", "como se pagan", "cómo se pagan",
        "como liber", "cómo liber", "domiciliacion", "domiciliación",
        "garantia", "garantía", "sin garantia", "sin garantía",
        "conversion", "conversión", "internacional",
    )
    # Definición aunque el texto diga tarjeta/cuota/límite
    _is_kb_definition = any(
        s in ql
        for s in (
            "que es", "qué es", "significa", "definicion", "definición",
            "explicame", "explícame", "cuentame", "cuéntame", "hablame", "háblame",
            "informacion sobre", "información sobre",
        )
    )
    # "mi tarjeta / mi saldo" = personal; "cuéntame sobre tarjeta de débito" = conocimiento
    has_personal_possessive = any(
        p in ql
        for p in (
            "mi tarjeta", "mis tarjetas", "mi cuenta", "mis cuentas",
            "mi prestamo", "mi préstamo", "mis prestamos", "mis préstamos",
            "mi saldo", "cuanto tengo", "cuánto tengo",
            "mis productos", "listado de mis", "dame mis productos",
            "informacion de mis", "información de mis",
            # RD: mis certificados / DAP son portafolio, no glosario de garantía
            "mis certificados", "mi certificado", "dame mis certificados",
            "dime mis certificados", "mis cdt", "mis dap",
            "mis depositos", "mis depósitos", "dame mis depositos", "dame mis depósitos",
        )
    )
    if has_personal_possessive and not any(s in ql for s in ("que es", "qué es", "definicion", "definición")) and not _is_kb_definition:
        return None
    # "tasa del préstamo 27615" tiene señal personal + knowledge: priorizar personal
    if any(s in ql for s in ("prestamo", "préstamo", "credito", "crédito")) and any(
        s in ql for s in ("tasa", "cuota", "mora", "capital", "saldo", "deuda", "vence")
    ) and not any(s in ql for s in ("que es", "qué es", "definicion", "definición", "significa")) and not _is_kb_definition:
        return None
    if any(s in ql for s in personal) and not any(s in ql for s in knowledge_signals) and not _is_kb_definition:
        return None

    from genesis_cognitive.router.knowledge_followup import (
        expand_knowledge_question,
        is_bank_responsibility_question,
        is_client_responsibility_question,
        is_knowledge_followup,
    )

    q_expanded = expand_knowledge_question(q, session)
    hit = match_faq(q_expanded if q_expanded != q else q)
    # Si el follow-up corto no matcheó, reintentar con pregunta ampliada
    if (hit is None or float((hit or {}).get("score") or 0) < 0.55) and q_expanded != q:
        hit2 = match_faq(q_expanded)
        if hit2 and float(hit2.get("score") or 0) >= float((hit or {}).get("score") or 0):
            hit = hit2
            q = q_expanded
    elif q_expanded != q:
        q = q_expanded

    # Preferir catálogo de tarjetas cuando la pregunta es específica (no "todos los productos")
    try:
        from genesis_cognitive.router.field_guardrails import is_bank_card_catalog_question

        if is_bank_card_catalog_question(q):
            entries = load_faq_entries(_default_faq_path())
            card_entry = next(
                (
                    e
                    for e in entries
                    if _entry_usable(e)
                    and str(e.get("id") or "") == "fase1-tarjetas-contratar"
                ),
                None,
            )
            if card_entry and card_entry.get("answer"):
                hit = {
                    "score": 0.99,
                    "entry": card_entry,
                    "answer": card_entry.get("answer"),
                    "topic": card_entry.get("topic"),
                    "id": card_entry.get("id"),
                }
    except Exception:
        pass

    # Responsabilidad del BANCO vs del CLIENTE (no mezclar ni caer en misión)
    if is_bank_responsibility_question(q) or (
        is_knowledge_followup(q)
        and session is not None
        and any(
            s in str(getattr(session, "last_knowledge_topic", "") or "").lower()
            for s in ("responsab", "derecho", "obligacion", "obligación")
        )
        and "banco" in _norm(q)
    ):
        entries = load_faq_entries(_default_faq_path())
        bank_entry = next(
            (
                e
                for e in entries
                if _entry_usable(e) and str(e.get("id") or "") == "fase1-responsabilidad-banco"
            ),
            None,
        )
        if bank_entry and bank_entry.get("answer"):
            hit = {
                "score": 0.99,
                "entry": bank_entry,
                "answer": bank_entry.get("answer"),
                "topic": bank_entry.get("topic"),
                "id": bank_entry.get("id"),
            }
    elif is_client_responsibility_question(q):
        entries = load_faq_entries(_default_faq_path())
        client_entry = next(
            (
                e
                for e in entries
                if _entry_usable(e)
                and str(e.get("id") or "") in ("fase1-responsabilidad-cliente", "vf01-r321")
            ),
            None,
        )
        if client_entry and client_entry.get("answer"):
            hit = {
                "score": 0.99,
                "entry": client_entry,
                "answer": client_entry.get("answer"),
                "topic": client_entry.get("topic"),
                "id": client_entry.get("id"),
            }


    # Proceso para contratar (no reclamaciones)
    qn = _norm(q)
    if any(s in qn for s in ("proceso para contratar", "proceso de contratacion", "proceso de contratación", "como contrato un producto", "como contratar un producto")) and "reclam" not in qn:
        entries = load_faq_entries(_default_faq_path())
        contr = next((e for e in entries if str(e.get("id") or "") == "fase1-proceso-contratar" and _entry_usable(e)), None)
        if contr and contr.get("answer"):
            hit = {
                "score": 0.99,
                "entry": contr,
                "answer": contr.get("answer"),
                "topic": contr.get("topic"),
                "id": contr.get("id"),
            }

    # Combo misión+visión (u otras institucionales): no dejar que un solo topic del
    # intent resolver pise la respuesta combinada.
    faq_is_combo = bool(hit and "+" in str(hit.get("id") or "")) or (
        bool(hit) and len(_asked_institutional_parts(q)) >= 2 and " / " in str(hit.get("topic") or "")
    )

    # Preferir KB de fallecidos cuando la pregunta lo menciona (evita match a "Cliente")
    qn = _norm(q)
    if "fallecid" in qn or "fallecimiento" in qn:
        entries = load_faq_entries(_default_faq_path())
        fallecido = next(
            (
                e
                for e in entries
                if _entry_usable(e)
                and (
                    "fallecid" in _norm(e.get("topic") or "")
                    or "fallecid" in _norm(e.get("intent") or "")
                    or str(e.get("id") or "") == "vf01-r324"
                )
            ),
            None,
        )
        if fallecido and fallecido.get("answer"):
            hit = {
                "score": 0.99,
                "entry": fallecido,
                "answer": fallecido.get("answer"),
                "topic": fallecido.get("topic"),
                "id": fallecido.get("id"),
            }
            faq_is_combo = False

    # Interpretar intención: puede ganar al FAQ cuando el match exacto es genérico
    # (ej. "tarjeta de crédito" vs "pago mínimo – tarjeta de crédito").
    intent_hit = None
    locked_ids = {
        "fase1-tarjetas-contratar",
        "fase1-proceso-contratar",
        "fase1-credito-diferido-contratar",
        "fase1-mision-y-vision",
        "fase1-productos-solicitar",
        "fase1-cuentas-contratar",
        "fase1-prestamos-contratar",
        "fase1-que-es-certificado-deposito",
        "fase1-responsabilidad-cliente",
        "fase1-responsabilidad-banco",
        "fase1-cuenta-ahorro-uso",
        "vf01-r321",
    }
    # No lockear respuesta de cliente si la pregunta es del banco
    if hit and str(hit.get("id") or "") in ("fase1-responsabilidad-cliente", "vf01-r321"):
        hit_locked_skip = is_bank_responsibility_question(q)
    else:
        hit_locked_skip = False
    # Consulta personal de producto (p. ej. «tarjeta joven») ≠ definición de «cliente»
    if hit and str(hit.get("id") or "") in ("fase1-responsabilidad-cliente", "vf01-r321"):
        if any(
            s in qn
            for s in (
                "mi tarjeta", "mis tarjetas", "tarjeta joven", "visa joven",
                "mi cuenta", "mi prestamo", "mi préstamo", "saldo de mi",
                "tasa de mi",
            )
        ):
            hit = None
            hit_locked_skip = False
    hit_locked = bool(hit and str(hit.get("id") or "") in locked_ids) and not hit_locked_skip
    if not faq_is_combo and not hit_locked:
        try:
            from genesis_cognitive.rag.kb_intent_resolver import resolve_knowledge_intent

            intent_min = float(os.getenv("GENESIS_KB_INTENT_FAQ_MIN_SCORE", "0.45"))
            focus = None
            if session is not None:
                focus = getattr(session, "last_knowledge_topic", None)
            # Solo reinyectar foco en follow-ups CORTOS sin producto explícito
            # (ej. "y el proceso?") — no en "condiciones del multicrédito"
            q_for_intent = q
            q_tokens = _tokens(q)
            has_product = any(
                s in qn
                for s in (
                    "multicredit", "diferido", "debito", "débito", "corriente",
                    "ahorro", "prestamo", "préstamo", "tarjeta", "certificado",
                )
            )
            short_followup = is_knowledge_followup(q) or (
                len(q_tokens) <= 5
                and any(
                    s in qn
                    for s in (
                        "proceso de solicitud",
                        "el proceso",
                        "y el proceso",
                        "requisito",
                        "como lo contrato",
                        "cómo lo contrato",
                        "y los cargos",
                        "y las condiciones",
                        "como se usa",
                        "cómo se usa",
                        "como funciona",
                        "cómo funciona",
                        "del banco",
                    )
                )
            )
            if focus and short_followup and not has_product:
                q_for_intent = (
                    q_expanded
                    if q_expanded != (question or "").strip()
                    else f"{q} {focus}"
                )
            intent_hit = resolve_knowledge_intent(
                q_for_intent,
                min_score=intent_min,
                knowledge_focus=focus if short_followup else None,
            )
        except Exception:
            intent_hit = None

    if intent_hit and intent_hit.get("answer") and not hit_locked:
        faq_score = float((hit or {}).get("score") or 0.0)
        intent_score = float(intent_hit.get("score") or 0.0)
        prefer_intent = (
            hit is None
            or intent_score >= faq_score + 0.05
            or (
                intent_score >= 0.85
                and _norm(intent_hit.get("topic") or "") != _norm((hit or {}).get("topic") or "")
                and len(_tokens(intent_hit.get("topic") or "")) >= len(_tokens((hit or {}).get("topic") or ""))
            )
        )
        # Definición / topic explícito: no dejar que MD genérico pise FAQ lexical fuerte
        faq_topic_n = _norm((hit or {}).get("topic") or "")
        intent_topic_n = _norm(intent_hit.get("topic") or "")
        q_topic_overlap = len(_tokens(faq_topic_n) & _tokens(qn)) if faq_topic_n else 0
        definitional = any(
            s in qn
            for s in (
                "que es", "que significa", "explicame", "hablame de", "cuentame",
                "dime que significa", "informacion sobre", "como funciona", "como funcionan",
                "conversion", "internacional",
            )
        )
        if hit and faq_score >= 0.78 and definitional and q_topic_overlap >= 2:
            prefer_intent = False
        if hit and faq_score >= 0.9:
            # FAQ muy específico (p.ej. conversión de moneda) gana a MD genérico
            prefer_intent = False
        if hit and faq_topic_n and intent_topic_n == faq_topic_n and faq_score >= intent_score:
            prefer_intent = False
        # Domiciliación / pago mínimo con producto en FAQ
        if hit and any(s in faq_topic_n for s in ("domiciliacion", "pago minimo", "conversion")):
            if "multicredit" not in qn and "cuotas bsc" not in qn:
                if "multicredit" in intent_topic_n and "multicredit" not in faq_topic_n:
                    prefer_intent = False
            prefer_intent = False
        # Nunca dejar que reclamaciones pisen contratación
        if "reclam" in _norm(intent_hit.get("topic") or "") and any(
            s in qn for s in ("contratar", "contrato", "solicitar producto")
        ) and "reclam" not in qn:
            prefer_intent = False
        if prefer_intent:
            hit = {
                "score": intent_score,
                "answer": intent_hit.get("answer"),
                "topic": intent_hit.get("topic"),
                "id": intent_hit.get("id"),
                "product": intent_hit.get("product"),
            }

    if not hit or not hit.get("answer"):
        return None

    # Definición explícita con hit irrelevante (topic ajeno) → abstenerse
    if not _definition_hit_is_relevant(q, hit):
        return None

    name = getattr(snapshot, "display_name", None) if snapshot is not None else None
    greeting = f"{name}, " if name else ""
    from genesis_cognitive.context.response_formatting import (
        append_digital_onboarding_link,
        sanitize_client_facing_text,
    )

    answer = sanitize_client_facing_text(str(hit["answer"]).strip())
    if not answer and hit.get("answer"):
        # Si el sanitizado vació un bloque MD, conservar cuerpo sin encabezado de ejemplos
        raw = str(hit["answer"])
        raw = re.sub(r"(?im)^\s*preguntas\s+ejemplo\s*:\s*$", "", raw)
        raw = re.sub(r"(?im)^\s*[-*•]\s+.*\?\s*$", "", raw)
        answer = sanitize_client_facing_text(raw.strip()) or raw.strip()
    # Nunca devolver respuestas meta de la matriz de pruebas
    if answer and any(
        s in answer.lower()
        for s in (
            "la ia cambia",
            "deja de utilizar el anterior",
            "validación esperada",
            "validacion esperada",
            "el asistente debe",
        )
    ):
        return None
    # Si la pregunta pide un detalle (p.ej. conversión) y el FAQ es genérico → dejar pasar a Foundry
    # Solo cuando NO hay match específico (evita tumbar respuestas overlay correctas)
    try:
        from genesis_cognitive.router.knowledge_followup import prefer_foundry_for_faq_hit

        topic_hit = _norm(str(hit.get("topic") or ""))
        specific_ok = any(
            s in topic_hit
            for s in ("conversion", "internacional", "joven", "infinite", "reclam", "pago minimo")
        )
        if (not specific_ok) and prefer_foundry_for_faq_hit(
            q, answer, score=float(hit.get("score") or 0)
        ):
            # No abstenerse en definiciones con FAQ lexical fuerte: el fallback
            # azure Search contaminaba con «Documento digital» (IG/CD campaña).
            keep_strong_definition = float(hit.get("score") or 0) >= 0.85 and any(
                s in ql
                for s in (
                    "que es", "qué es", "significa", "explicame", "explícame",
                    "definicion", "definición", "diferencia",
                )
            )
            if not keep_strong_definition:
                return None
    except Exception:
        pass
    if not answer:
        return None
    topic_n = _norm(str(hit.get("topic") or ""))
    intent_n = _norm(str(hit.get("intent") or ""))
    # Catálogo / contratar → siempre CTA digital
    if any(
        s in topic_n or s in intent_n or s in _norm(q)
        for s in (
            "contratar",
            "solicitar",
            "catalogo",
            "productos que puedes",
            "cuentas que puedes",
            "prestamos que puedes",
            "ofrece el banco",
            "tiene el banco",
        )
    ):
        answer = append_digital_onboarding_link(answer)
    text = f"{greeting}{answer}" if greeting and not answer.lower().startswith((name or "").lower()) else answer

    action = {
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
            "knowledge_topic": hit.get("topic"),
        },
        "missing_requirements": [],
        "depends_on": [],
        "confidence": float(hit.get("score") or 0.9),
    }
    return "VALID_CONTRACT", [action], text, None
