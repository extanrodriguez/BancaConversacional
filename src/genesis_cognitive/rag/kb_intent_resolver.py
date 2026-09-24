"""Resolución de intención sobre KB local cuando FAQ exacto no alcanza.

Flujo: FAQ miss → interpretar intención por solapamiento topic/expresiones/answer
→ devolver respuesta grounded (sin inventar). No sustituye Azure RAG; lo complementa
cuando no hay hits o el LLM declara datos insuficientes.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokens(text: str) -> set[str]:
    stop = {
        "de", "la", "el", "los", "las", "un", "una", "y", "o", "en", "del", "al",
        "por", "para", "con", "que", "se", "su", "sus", "es", "son", "como", "mas",
        "este", "esta", "cual", "cuales", "mi", "mis", "tu", "tus", "the", "a",
        "sobre", "dime", "explicame", "cuentame", "hablame", "quiero", "saber",
        "tiene", "tienen", "banco", "santa", "cruz", "bsc",
    }
    return {w for w in _norm(text).split() if len(w) > 2 and w not in stop}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=2)
def _load_corpus(faq_path: str) -> tuple[dict[str, Any], ...]:
    p = Path(faq_path)
    entries: list[dict[str, Any]] = []
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        for e in data.get("entries") or []:
            ans = (e.get("answer") or "").strip()
            if len(ans) < 40:
                continue
            low = ans.lower()
            if "basada exclusivamente" in low or "[respuesta" in low:
                continue
            if "la misma respuesta funcional" in low:
                continue
            if low.startswith("tema de informacion") or low.startswith("tema de información"):
                continue
            entries.append(
                {
                    "id": e.get("id"),
                    "topic": e.get("topic") or "",
                    "product": e.get("product") or "",
                    "intent": e.get("intent") or "",
                    "expressions": list(e.get("expressions") or []),
                    "answer": ans,
                    "source": "faq",
                }
            )

    # Overlay
    overlay = os.getenv("GENESIS_FAQ_OVERLAY_PATH", "").strip()
    if not overlay:
        overlay = str(p.with_name("kb_faq_overlay_fase1.json")) if p.name else ""
    op = Path(overlay) if overlay else None
    if op and op.is_file():
        extra = json.loads(op.read_text(encoding="utf-8"))
        by_id = {e["id"]: i for i, e in enumerate(entries) if e.get("id")}
        for e in extra.get("entries") or []:
            eid = e.get("id")
            if eid and eid in by_id:
                cur = entries[by_id[eid]]
                cur["expressions"] = list(dict.fromkeys(cur["expressions"] + list(e.get("expressions") or [])))
                if e.get("answer") and len(str(e["answer"])) > len(cur["answer"]):
                    cur["answer"] = str(e["answer"]).strip()
                if e.get("synonyms"):
                    cur["expressions"] = list(
                        dict.fromkeys(cur["expressions"] + list(e.get("synonyms") or []))
                    )
            elif e.get("answer") and len(str(e.get("answer") or "")) >= 40:
                entries.append(
                    {
                        "id": eid,
                        "topic": e.get("topic") or "",
                        "product": e.get("product") or "",
                        "intent": e.get("intent") or "",
                        "expressions": list(e.get("expressions") or []) + list(e.get("synonyms") or []),
                        "answer": str(e["answer"]).strip(),
                        "source": "overlay",
                    }
                )

    # Markdown KB sections (topic = ## heading)
    kb_dir = Path(os.getenv("GENESIS_KB_DIR", str(_repo_root() / "Knowledge_Base" / "excel_vf01")))
    if kb_dir.is_dir():
        for md in kb_dir.glob("*.md"):
            try:
                body = md.read_text(encoding="utf-8")
            except OSError:
                continue
            chunks = re.split(r"(?m)^##\s+", body)
            for chunk in chunks[1:]:
                lines = chunk.strip().splitlines()
                if not lines:
                    continue
                topic = lines[0].strip()
                answer = "\n".join(lines[1:]).strip()
                if len(answer) < 40:
                    continue
                # Excluir filas de matriz de prueba (respuestas simuladas personales)
                topic_l = topic.lower()
                ans_l = answer.lower()
                if re.match(r"^fila\s+\d+", topic_l) or "respuesta / contexto aprobado" in ans_l:
                    continue
                if re.search(r"terminada en\s+\d{3,}", ans_l) and re.search(
                    r"(tienes|tu)\s+rd\$|saldo actual de tu|disponibles en tu",
                    ans_l,
                ):
                    continue
                entries.append(
                    {
                        "id": f"md-{md.stem}-{_norm(topic)[:40]}",
                        "topic": topic,
                        "product": md.stem,
                        "intent": "Consultar conocimiento",
                        "expressions": [topic, f"qué es {topic}", f"que es {topic}"],
                        "answer": answer,
                        "source": "markdown",
                    }
                )

    return tuple(entries)


def clear_kb_intent_cache() -> None:
    _load_corpus.cache_clear()


_PRODUCT_ANCHORS = (
    "multicredit",
    "multi credito",
    "credito diferido",
    "cuotas bsc",
    "tarjeta de debito",
    "tarjeta de credito",
    "cuenta corriente",
    "cuenta de ahorro",
    "prestamo",
    "deposito a plazo",
    "certificado de deposito",
    "certificado",
    "deposito",
)

# Anclas DAP: no deben “enganchar” documentos de préstamos que solo mencionan
# certificados como garantía colateral.
_DAP_DEFINITION_ANCHORS = (
    "certificado de deposito",
    "certificados de deposito",
    "deposito a plazo",
    "depositos a plazo",
    "certificado",
    "dap",
    "cdt",
)


def _asked_product_anchor(qn: str) -> str | None:
    for a in _PRODUCT_ANCHORS:
        if a in qn:
            return a
    return None


def _is_dap_definition_question(qn: str) -> bool:
    if not any(a in qn for a in _DAP_DEFINITION_ANCHORS):
        return False
    # Excluir préstamo con garantía de certificados
    if any(k in qn for k in ("prestamo", "credito", "garantia", "financi")):
        return False
    return bool(
        re.search(r"\b(que es|que significa|definicion|hablame de|cuentame de)\b", qn)
        or qn.strip() in {
            "certificado de deposito",
            "certificados de deposito",
            "deposito a plazo",
            "depositos a plazo",
            "certificado",
            "dap",
            "cdt",
        }
        or qn.startswith("certificado")
        or "deposito a plazo" in qn
    )


def _entry_is_dap_product(entry: dict[str, Any]) -> bool:
    blob = _norm(
        f"{entry.get('topic') or ''} {entry.get('product') or ''} "
        f"{' '.join(entry.get('expressions') or [])}"
    )
    if any(k in blob for k in ("deposito a plazo", "certificado de deposito", "depositos / certificados")):
        return True
    if "prestamo" in blob or "credito" in blob or "garantia certificado" in blob:
        return False
    return "certificado" in blob and "garantia" not in blob and "prestamo" not in blob


def _score_intent(question: str, entry: dict[str, Any]) -> float:
    qn = _norm(question)
    qt = _tokens(question)
    if not qn or not qt:
        return 0.0
    best = 0.0
    topic = _norm(entry.get("topic") or "")
    topic_toks = _tokens(entry.get("topic") or "")
    product = _norm(entry.get("product") or "")
    answer_n = _norm((entry.get("answer") or "")[:500])

    for expr in entry.get("expressions") or []:
        en = _norm(expr)
        if not en:
            continue
        if qn == en:
            return 1.0
        # Expresión genérica corta sin anclar producto (ej. "condiciones de uso")
        et = _tokens(expr)
        if len(et) <= 2 and en in qn and not any(a in en for a in _PRODUCT_ANCHORS):
            # Solo cuenta si el producto del entry también está en la pregunta
            if product and not any(p in qn for p in product.split() if len(p) > 4):
                continue
        if en in qn or qn in en:
            best = max(best, 0.92)
            continue
        if et and len(et) >= 2:
            best = max(best, len(qt & et) / max(len(et), 1) * 0.9)
        elif et and len(et) == 1:
            # Expresión colapsada a 1 token (ej. "banco") — no puntuar alto
            best = max(best, 0.15)

    if topic_toks:
        overlap = len(qt & topic_toks) / max(len(topic_toks), 1)
        best = max(best, overlap * 0.95)
        if topic and topic in qn:
            best = max(best, 0.9)
        # Topic genérico de 1 palabra (Cargo, Cliente) no debe ganar por substring
        if len(topic_toks) == 1 and topic and topic in qn:
            alone = next(iter(topic_toks))
            if alone in {"cargo", "cargos", "cliente", "banco", "tasa", "pago"}:
                if not any(a in qn for a in _PRODUCT_ANCHORS if a in (product + " " + topic)):
                    best = min(best, 0.35)

    # solapamiento con respuesta: peso bajo (evita "cuenta corriente" dentro de definición de débito)
    ans_toks = _tokens((entry.get("answer") or "")[:400])
    if ans_toks and qt:
        ans_overlap = len(qt & ans_toks) / max(len(qt), 1) * 0.35
        # Si la pregunta pide definición de X y X no está en el topic, no boost por answer
        if re.search(r"\b(que es|que significa|definicion)\b", qn):
            asked = qt - {"cuenta", "tarjeta", "producto", "servicio"}
            if asked and topic_toks and not (asked & topic_toks):
                ans_overlap *= 0.2
        best = max(best, ans_overlap)

    if product and any(p in qn for p in product.split() if len(p) > 4):
        best = max(best, best * 1.08 if best else 0.25)

    # Ancla de producto en la pregunta vs producto del entry
    anchor = _asked_product_anchor(qn)
    if anchor:
        blob = f"{topic} {product} {answer_n}"
        anchored_in_meta = anchor in topic or anchor in product or any(
            tok in topic or tok in product for tok in anchor.split() if len(tok) > 4
        )
        anchored_in_answer = anchor in answer_n or any(
            tok in answer_n for tok in anchor.split() if len(tok) > 4
        )
        if anchored_in_meta:
            best = max(best, best * 1.2 if best >= 0.2 else 0.55)
        elif anchored_in_answer:
            # Mención incidental en el cuerpo (p. ej. préstamo con garantía de certificado)
            # NO inventar score 0.55 desde casi cero.
            if best >= 0.25:
                best = max(best, best * 1.05)
            else:
                best *= 0.5
        else:
            # Entry de otro producto → penalizar fuerte
            best *= 0.25

    # Definición de certificado/DAP: nunca devolver condiciones de préstamos
    if _is_dap_definition_question(qn):
        if _entry_is_dap_product(entry):
            best = max(best, 0.88 if best < 0.88 else best)
        else:
            loanish = any(
                k in f"{topic} {product}"
                for k in (
                    "prestamo",
                    "credito",
                    "consumo",
                    "hipotec",
                    "condiciones financieras",
                    "cargos, comisiones",
                    "garantia",
                )
            )
            if loanish or "garantia certificado" in _norm(f"{topic} {answer_n[:200]}"):
                best *= 0.08
            elif "certificado" in answer_n or "deposito" in answer_n:
                # mención colateral en otro producto
                best *= 0.15

    # Contratar / solicitar: no reclamaciones; priorizar catálogo/proceso
    if any(k in qn for k in ("contratar", "contrato", "solicitar", "solicitud", "puedo abrir", "proceso para contratar")):
        if "reclam" in topic or "reclam" in product or "queja" in topic:
            if "reclam" not in qn and "queja" not in qn:
                best *= 0.15
        if any(k in topic or k in product for k in ("contratar", "solicitar", "catalogo", "producto", "apertura", "onboarding")):
            best = max(best, best * 1.25 if best else 0.55)

    # Cómo contrato / proceso → preferir proceso sobre "qué es"
    if any(k in qn for k in ("como contrato", "como contratar", "como solicito", "proceso de", "proceso para")):
        if topic.startswith("que es") or topic in {"credito diferido", "cargo", "tarjeta de debito"}:
            if "proceso" not in topic and "document" not in topic and "solicitud" not in topic:
                best *= 0.4
        if any(k in topic for k in ("proceso", "solicitud", "documentacion", "apertura", "requisito")):
            best = max(best, best * 1.3 if best else 0.6)

    # Evitar que "banco" genérico gane sobre catálogo de productos
    if any(k in qn for k in (
        "contratar", "puedo abrir", "productos de", "tipos de", "tarjeta", "tarjetas",
        "ofrece el banco", "tiene el banco", "debito", "credito",
    )):
        if topic in ("banco santa cruz", "mision", "vision") or topic.startswith("banco santa"):
            best *= 0.2

    # Pregunta de préstamos a contratar: penalizar catálogo de cuentas
    if "prestamo" in qn or "préstamo" in qn:
        if "cuenta" in topic and "prestamo" not in topic and "préstamo" not in topic:
            best *= 0.25
        if "prestamo" in topic or "préstamo" in topic or "credito" in topic or "crédito" in topic:
            best = max(best, best * 1.15 if best else 0.5)

    # Responsabilidad / derechos → no about-us ni definición de "Cliente"
    if any(k in qn for k in ("responsabilidad", "derecho", "deber", "obligacion", "obligaciones", "como cliente")):
        if topic.startswith("banco santa") or topic in ("mision", "vision", "cliente"):
            best *= 0.15
        if topic == "cliente" or product.startswith("banco santa cruz / general") and "cliente" in topic:
            best *= 0.1
        if any(k in topic for k in ("derecho", "obligacion", "responsabilidad", "deber", "usuario")):
            best = max(best, best * 1.35 if best else 0.65)
        # Follow-up "la mía como cliente" con foco previo
        if any(k in qn for k in ("la mia", "la mía", "las mias", "las mías", "y la mia", "y la mía", "como cliente")):
            if any(k in topic for k in ("derecho", "obligacion", "responsabilidad", "deber", "usuario")):
                best = max(best, 0.92)
            if topic == "cliente":
                best *= 0.05

    return min(best, 1.0)


def resolve_knowledge_intent(
    question: str,
    *,
    faq_path: str | None = None,
    min_score: float = 0.32,
    knowledge_focus: str | None = None,
) -> dict[str, Any] | None:
    """Interpreta la intención contra el corpus KB y devuelve la mejor respuesta grounded."""
    path = faq_path or os.getenv("GENESIS_FAQ_PATH", "")
    if not path:
        path = str(_repo_root() / "data" / "kb_faq_vf01.json")
    corpus = _load_corpus(path)
    if not corpus:
        return None

    q_eff = question
    if knowledge_focus:
        q_eff = f"{question} {knowledge_focus}"

    scored = [(_score_intent(q_eff, e), e) for e in corpus]
    scored.sort(key=lambda x: (x[0], len(x[1].get("answer") or "")), reverse=True)
    top_score, top = scored[0]
    if top_score < min_score:
        return None

    # Desambiguación: si hay empate cercano, preferir topic con más tokens de la pregunta
    if len(scored) > 1 and abs(scored[1][0] - top_score) < 0.04:
        qt = _tokens(q_eff)

        def topic_fit(e: dict[str, Any]) -> float:
            tt = _tokens(e.get("topic") or "")
            return len(qt & tt) / max(len(tt), 1) if tt else 0.0

        a, b = scored[0][1], scored[1][1]
        if topic_fit(b) > topic_fit(a) + 0.15:
            top = b
            top_score = scored[1][0]

    return {
        "score": top_score,
        "topic": top.get("topic"),
        "id": top.get("id"),
        "answer": top.get("answer"),
        "product": top.get("product"),
        "source": top.get("source"),
        "intent": top.get("intent"),
    }


def is_business_knowledge_question(question: str) -> bool:
    """Heurística: pregunta de conocimiento/producto (no saldo personal)."""
    q = _norm(question)
    if not q:
        return False
    personal = (
        "mi saldo", "mis productos", "mi cuenta", "mi tarjeta", "mi prestamo",
        "mi préstamo", "cuanto tengo", "cuánto tengo", "transfer",
    )
    if any(p in q for p in personal):
        return False
    knowledge = (
        "que es", "que significa", "requisito", "proceso", "cargo", "comision",
        "derecho", "deber", "reclam", "tarjeta", "prestamo", "credito",
        "contratar", "solicitar", "multicredit", "diferido", "tarifario",
        "certificado", "deposito", "dap", "cdt",
    )
    return any(k in q for k in knowledge)
