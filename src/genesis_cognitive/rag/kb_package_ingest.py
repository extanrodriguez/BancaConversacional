"""Adaptador de ingestión del paquete BSC_Potenciacion_Lunes.

Convierte fichas/chunks QA elegibles en:
- Overlay FAQ compatible con faq_guardrail (sin indexar pruebas ni reglas).
- Corpus local versionado para recuperación por faceta.
- Diff de publicación hacia Azure AI Search (sin --force ni borrado del índice).

No declara aprobación de producción: las fichas traen approval_status.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

PACKAGE_VERSION = "bsc-kb-2026-09-19-candidate-1"
DEFAULT_PACKAGE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "works"
    / "insumos"
    / "BSC_Potenciacion_Lunes"
)


def package_root() -> Path:
    env = (os.getenv("GENESIS_KB_PACKAGE_ROOT") or "").strip()
    return Path(env) if env else DEFAULT_PACKAGE_ROOT


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def load_qa_chunks(*, root: Path | None = None) -> list[dict[str, Any]]:
    root = root or package_root()
    chunks = _read_jsonl(root / "kb" / "chunks_qa.jsonl")
    return [c for c in chunks if c.get("qa_eligible") is True]


def load_qa_fichas(*, root: Path | None = None) -> list[dict[str, Any]]:
    root = root or package_root()
    fichas = _read_jsonl(root / "kb" / "fichas_qa.jsonl")
    return [f for f in fichas if f.get("qa_eligible") is True]


def _norm(text: str) -> str:
    t = (text or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _faq_id_for_chunk(chunk: dict[str, Any]) -> str:
    parent = str(chunk.get("parent_id") or chunk.get("id") or "").strip()
    if parent.startswith("vf01-r") and parent.count("-") == 1:
        # vf01-r262 → vf01-r262 (FAQ usa vf01-r262 sin cero a la izquierda en algunos)
        row = parent.split("-r", 1)[-1]
        try:
            return f"vf01-r{int(row)}"
        except ValueError:
            return parent
    return parent or str(chunk.get("id"))


_KIND_INTENT = {
    "definition": "Consultar definición o concepto",
    "product_knowledge": "Consultar características de producto",
    "procedure": "Consultar procedimiento",
    "scoped_editorial_summary": "Consultar orientación de proceso",
    "public_reference": "Consultar referencia pública",
}


def _expressions_for(chunk: dict[str, Any]) -> list[str]:
    title = str(chunk.get("title") or "").strip()
    kind = str(chunk.get("content_kind") or "")
    exprs = [title] if title else []
    tn = _norm(title)
    if kind in ("definition", "product_knowledge") and title:
        exprs.extend([
            f"qué es {title}",
            f"que es {title}",
            f"características de {title}",
            f"caracteristicas de {title}",
            f"información de {title}",
            f"informacion de {title}",
            f"dime sobre {title}",
        ])
    if kind in ("procedure", "scoped_editorial_summary"):
        if "reclam" in tn:
            exprs.extend([
                "cómo reclamo",
                "como reclamo",
                "proceso de reclamación",
                "proceso de reclamacion",
                "quiero hacer una reclamación",
                "quiero hacer una reclamacion",
                "cómo presento una reclamación",
            ])
        if "fallec" in tn:
            exprs.extend([
                "falleció mi esposo",
                "fallecio mi esposo",
                "procedimiento por fallecimiento",
                "retiro de fondos de fallecidos",
                "qué hago si fallece un familiar",
            ])
        if "cancel" in tn:
            exprs.extend([
                "cómo cancelo un préstamo",
                "proceso de cancelación",
                "proceso de cancelacion",
                "cómo cancelar mi tarjeta",
            ])
    if "joven" in tn and "debito" in tn:
        exprs.extend(["visa joven débito", "tarjeta de débito joven", "débito joven"])
    if "joven" in tn and "credito" in tn:
        exprs.extend(["visa joven", "tarjeta joven", "características de visa joven", "qué es visa joven"])
    # dedupe
    seen: set[str] = set()
    out: list[str] = []
    for e in exprs:
        k = _norm(e)
        if k and k not in seen:
            seen.add(k)
            out.append(e)
    return out


def chunk_to_faq_entry(chunk: dict[str, Any]) -> dict[str, Any]:
    title = str(chunk.get("title") or "").strip()
    content = str(chunk.get("content") or "").strip()
    kind = str(chunk.get("content_kind") or "definition")
    return {
        "id": _faq_id_for_chunk(chunk),
        "chunk_id": chunk.get("id"),
        "parent_id": chunk.get("parent_id"),
        "row": (chunk.get("source_rows") or [None])[0],
        "topic": title,
        "product": str(chunk.get("domain") or "Banco Santa Cruz"),
        "intent": _KIND_INTENT.get(kind, "Consultar información"),
        "content_kind": kind,
        "domain": chunk.get("domain"),
        "expressions": _expressions_for(chunk),
        "synonyms": [title] if title else [],
        "answer": content,
        "source": f"BSC_Potenciacion_Lunes/{PACKAGE_VERSION}",
        "version": chunk.get("version") or PACKAGE_VERSION,
        "qa_eligible": True,
        "approval_status": chunk.get("approval_status") or "approval_not_evidenced",
        "approved_for_prod": bool(chunk.get("approved_for_prod")),
        "source_rows": chunk.get("source_rows") or [],
    }


def build_faq_overlay(*, root: Path | None = None) -> dict[str, Any]:
    """Overlay FAQ desde chunks QA. No incluye fichas_candidatas ni evaluación."""
    chunks = load_qa_chunks(root=root)
    # Preferir el cuerpo más largo por FAQ id (evita título corto pisando procedimiento)
    by_id: dict[str, dict[str, Any]] = {}
    for ch in chunks:
        entry = chunk_to_faq_entry(ch)
        eid = entry["id"]
        prev = by_id.get(eid)
        if prev is None or len(entry.get("answer") or "") > len(prev.get("answer") or ""):
            by_id[eid] = entry
        else:
            # fusionar expresiones
            exprs = list(dict.fromkeys((prev.get("expressions") or []) + (entry.get("expressions") or [])))
            prev["expressions"] = exprs
    entries = list(by_id.values())
    return {
        "version": f"potenciacion-lunes-{PACKAGE_VERSION}",
        "description": (
            "Overlay generado desde kb/chunks_qa.jsonl. "
            "No indexa evaluacion/, catalogo/, estrategia/ ni fichas_candidatas. "
            "approval_status=approval_not_evidenced salvo evidencia previa."
        ),
        "corpus_version": PACKAGE_VERSION,
        "count": len(entries),
        "entries": entries,
    }


def write_faq_overlay(
    out_path: Path | None = None,
    *,
    root: Path | None = None,
) -> Path:
    overlay = build_faq_overlay(root=root)
    dest = out_path or (
        Path(__file__).resolve().parents[3] / "data" / "kb_faq_overlay_potenciacion_lunes.json"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def write_local_corpus(
    out_dir: Path | None = None,
    *,
    root: Path | None = None,
) -> Path:
    """Corpus local versionado para retrieval por faceta (sin Azure)."""
    root = root or package_root()
    chunks = load_qa_chunks(root=root)
    dest = out_dir or (
        Path(__file__).resolve().parents[3]
        / "data"
        / "kb_corpus"
        / PACKAGE_VERSION
    )
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "corpus_version": PACKAGE_VERSION,
        "chunk_count": len(chunks),
        "source_package": str(root),
        "qa_eligible_only": True,
        "excluded": [
            "kb/fichas_candidatas.jsonl",
            "evaluacion/*",
            "estrategia/*",
            "catalogo/*",
            "revision/*",
        ],
        "sha256_chunks": hashlib.sha256(
            (dest / "chunks.jsonl").read_bytes()
        ).hexdigest(),
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return dest


def build_search_documents(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Documentos listos para Azure AI Search (publicación opcional, sin --force)."""
    docs = []
    for ch in load_qa_chunks(root=root):
        docs.append({
            "id": ch["id"],
            "parent_id": ch.get("parent_id"),
            "title": ch.get("title"),
            "content": ch.get("content"),
            "domain": ch.get("domain"),
            "content_kind": ch.get("content_kind"),
            "version": ch.get("version") or PACKAGE_VERSION,
            "qa_eligible": True,
            "approval_status": ch.get("approval_status"),
            "approved_for_prod": bool(ch.get("approved_for_prod")),
            "source_rows": ch.get("source_rows") or [],
            "language": ch.get("language") or "es-DO",
        })
    return docs


def write_search_publish_bundle(out_dir: Path | None = None, *, root: Path | None = None) -> Path:
    dest = out_dir or (
        Path(__file__).resolve().parents[3]
        / "data"
        / "kb_publish"
        / PACKAGE_VERSION
    )
    dest.mkdir(parents=True, exist_ok=True)
    docs = build_search_documents(root=root)
    (dest / "documents.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n",
        encoding="utf-8",
    )
    (dest / "PUBLISH.md").write_text(
        "\n".join([
            f"# Bundle Azure AI Search — {PACKAGE_VERSION}",
            "",
            "Índice sugerido (paralelo, no reemplazo): `genesis-kb-qa-20260919`",
            "No usar `--force`. No borrar el índice vigente.",
            "Activación: apuntar `AZURE_SEARCH_INDEX` / Foundry al índice QA y reiniciar.",
            "Reversión: restaurar el índice anterior en la misma variable.",
            f"Documentos: {len(docs)} (solo qa_eligible).",
            "approval_status: approval_not_evidenced — no declarar prod.",
            "",
        ]),
        encoding="utf-8",
    )
    return dest


def local_retrieve(
    question: str,
    *,
    content_kinds: list[str] | None = None,
    limit: int = 3,
    root: Path | None = None,
    required_product: str | None = None,
) -> list[dict[str, Any]]:
    """Recuperación léxica local por faceta (sin LLM).

    Aplica filtro de producto cuando la pregunta o `required_product` lo exigen:
    un chunk de Visa Joven no responde consultas Platinum.
    """
    qn = _norm(question)
    q_tokens = {w for w in qn.split() if len(w) > 2}
    wanted = _norm(required_product or "") or _infer_product_want(qn)
    hits: list[tuple[float, dict[str, Any]]] = []
    for ch in load_qa_chunks(root=root):
        kind = str(ch.get("content_kind") or "")
        if content_kinds and kind not in content_kinds:
            continue
        title = _norm(str(ch.get("title") or ""))
        body = _norm(str(ch.get("content") or ""))
        blob = f"{title} {body}"
        # Aplicabilidad producto: rechazo cruzado duro
        if wanted and not _chunk_applies(wanted, blob, title):
            continue
        score = 0.0
        if title and title in qn:
            score += 1.2
        if title and any(tok in qn for tok in title.split() if len(tok) >= 5):
            score += 0.6
        overlap = len(q_tokens & set(body.split())) / max(len(q_tokens), 1)
        score += overlap
        if kind in ("procedure", "scoped_editorial_summary", "product_knowledge"):
            score += 0.25
        if title == "cliente" and "cliente" not in qn.split():
            score -= 1.0
        if wanted and wanted in blob:
            score += 0.4
        if score >= 0.35:
            hits.append((score, ch))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [h[1] for h in hits[:limit]]


_PRODUCT_MARKERS: dict[str, tuple[str, ...]] = {
    "visa_platinum": ("platinum", "platino"),
    "visa_infinite": ("infinite",),
    "visa_gold": ("gold", " oro"),
    "visa_joven": ("joven",),
    "visa_clasica": ("clasica", "clásica", "clasico"),
    "multicredito": ("multicredit", "credito diferido", "crédito diferido"),
    "cuenta_ahorros": ("cuenta de ahorro", "cuenta ahorro", "ahorros"),
    "cuenta_corriente": ("cuenta corriente", "corriente"),
}


def _infer_product_want(qn: str) -> str:
    for key, markers in _PRODUCT_MARKERS.items():
        if any(m.strip() in qn for m in markers):
            return key
    return ""


def _chunk_applies(wanted: str, blob: str, title: str) -> bool:
    markers = _PRODUCT_MARKERS.get(wanted) or ()
    has_wanted = any(m.strip() in blob for m in markers if m.strip())
    if not has_wanted and wanted.replace("_", " ") not in blob:
        # Chunk genérico bancario (misión, reclamación) permitido si no es ficha rival
        rival_hit = False
        for other, om in _PRODUCT_MARKERS.items():
            if other == wanted:
                continue
            if any(m.strip() in title for m in om if len(m.strip()) >= 4):
                rival_hit = True
                break
        return not rival_hit
    # Si el título es claramente de otro producto → rechazo
    for other, om in _PRODUCT_MARKERS.items():
        if other == wanted:
            continue
        if any(m.strip() in title for m in om if len(m.strip()) >= 4) and not has_wanted:
            return False
    return True
