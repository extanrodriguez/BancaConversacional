# -*- coding: utf-8 -*-
"""Azure AI Search retrieve — índice existente bsc-kb-conocimiento (solo lectura).

No reindexa ni escribe. Etiqueta search_mode=text|hybrid según capacidades reales.
"""
from __future__ import annotations

import os
import re
import time
from functools import lru_cache
from typing import Any


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def search_enabled() -> bool:
    return _env("GENESIS_SEARCH_RETRIEVE", "0").lower() in ("1", "true", "yes", "on")


def _endpoint() -> str:
    return _env("AZURE_SEARCH_ENDPOINT").rstrip("/")


def _index() -> str:
    return _env("AZURE_SEARCH_INDEX", "bsc-kb-conocimiento")


def _api_key() -> str:
    return _env("AZURE_SEARCH_API_KEY")


def _looks_like_matrix_simulation(text: str, title: str = "") -> bool:
    t = f"{title}\n{text}".lower()
    if re.search(r"fila\s+\d+", t) or "respuesta / contexto aprobado" in t:
        return True
    if re.search(r"terminada en\s+\d{3,}", t) and re.search(
        r"(tienes|tu)\s+rd\$|disponibles en tu|saldo actual de tu",
        t,
    ):
        return True
    if "datos simulados" in t or "entrada técnica" in t or "entrada tecnica" in t:
        return True
    return False


@lru_cache(maxsize=1)
def _index_has_vector() -> bool:
    """Detecta content_vector en el índice (una vez por proceso)."""
    ep, idx, key = _endpoint(), _index(), _api_key()
    if not (ep and idx and key):
        return False
    try:
        import httpx

        r = httpx.get(
            f"{ep}/indexes/{idx}?api-version=2024-07-01",
            headers={"api-key": key},
            timeout=20.0,
        )
        if r.status_code != 200:
            return False
        names = {f.get("name") for f in (r.json().get("fields") or [])}
        return "content_vector" in names
    except Exception:
        return False


def _embed(text: str) -> list[float] | None:
    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            api_key=_env("AZURE_OPENAI_API_KEY") or _env("OPENAI_API_KEY"),
            api_version=_env("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_endpoint=_env("AZURE_OPENAI_ENDPOINT").rstrip("/") + "/",
        )
        deployment = _env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
        resp = client.embeddings.create(model=deployment, input=text[:8000])
        return list(resp.data[0].embedding)
    except Exception:
        return None


def _build_odata_filter(
    *,
    product_filter: str | None = None,
    document_types: list[str] | None = None,
) -> str | None:
    """Filtro OData estricto: tipo de doc + producto (product/title)."""
    parts: list[str] = []
    if document_types:
        safe_types = []
        for dt in document_types:
            s = str(dt).replace("'", "''")[:80]
            if s:
                safe_types.append(f"document_type eq '{s}'")
        if safe_types:
            parts.append("(" + " or ".join(safe_types) + ")")
    if product_filter:
        safe = product_filter.replace("'", "''")[:80]
        # product + title (índice candidato usa product=domain a veces)
        parts.append(
            f"(search.ismatch('{safe}', 'product') or search.ismatch('{safe}', 'title')"
            f" or search.ismatch('{safe}', 'content'))"
        )
    if not parts:
        return None
    return " and ".join(parts)


def _rerank_hits(
    hits: list[dict[str, Any]],
    *,
    query: str,
    product_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Rerank léxico ligero: prioriza título/producto alineado al filtro/query."""
    qn = re.sub(r"\s+", " ", (query or "").lower()).strip()
    pf = (product_filter or "").lower().strip()

    def score(h: dict[str, Any]) -> float:
        title = str(h.get("title") or "").lower()
        product = str(h.get("product") or "").lower()
        content = str(h.get("content") or "").lower()
        base = float(h.get("score") or 0.0)
        bonus = 0.0
        if pf:
            if pf in title:
                bonus += 2.0
            if pf in product:
                bonus += 1.2
            if pf in content[:400]:
                bonus += 0.4
        # tokens de query en título
        for tok in qn.split():
            if len(tok) >= 5 and tok in title:
                bonus += 0.25
        dtype = str(h.get("document_type") or "")
        if dtype in ("product_knowledge", "definition", "procedure"):
            bonus += 0.15
        # Alineación tópico institucional: preferir fichas Misión/Visión
        # frente a contacto/web genérico cuando la query es institucional.
        if any(t in qn for t in ("mision", "misión", "vision", "visión")):
            if any(t in title for t in ("misión", "mision", "visión", "vision")):
                bonus += 3.5
            if "contacto" in title or "sucursal" in title or "teléfono" in title or "telefono" in title:
                bonus -= 2.0
            if content.startswith("somos una institución") or content.startswith("ser el banco preferido"):
                bonus += 1.5
        return base + bonus

    return sorted(hits, key=score, reverse=True)


def azure_search_retrieve(
    query: str,
    *,
    top: int = 5,
    product_filter: str | None = None,
    document_types: list[str] | None = None,
    prefer_hybrid: bool = True,
) -> dict[str, Any]:
    """Consulta real al índice. Devuelve hits sanitizados + metadatos de modo.

    No inventa contenido. Si falla, hits=[] y error tipado.
    """
    t0 = time.perf_counter()
    ep, idx, key = _endpoint(), _index(), _api_key()
    out: dict[str, Any] = {
        "provider": "azure_search",
        "index": idx,
        "search_mode": "none",
        "query": (query or "")[:240],
        "hits": [],
        "latency_ms": 0,
        "http": None,
        "error": None,
        "real_query": False,
        "filters": {
            "product_filter": product_filter,
            "document_types": list(document_types or []),
        },
    }
    if not search_enabled():
        out["error"] = "GENESIS_SEARCH_RETRIEVE_off"
        return out
    if not (ep and idx and key and (query or "").strip()):
        out["error"] = "missing_config_or_query"
        return out

    select = (
        "id,parent_id,title,content,document_type,product,functionality,intent,"
        "source_row,source_file,source_scope,source_section,status"
    )
    # Pedir más candidatos para rerank local
    fetch_top = max(1, min(max(int(top) * 4, 12), 40))
    body: dict[str, Any] = {
        "search": query,
        "top": fetch_top,
        "count": True,
        "select": select,
        "queryType": "simple",
    }
    odata = _build_odata_filter(
        product_filter=product_filter, document_types=document_types
    )
    if odata:
        body["filter"] = odata

    mode = "text"
    if prefer_hybrid and _index_has_vector():
        emb = _embed(query)
        if emb:
            body["vectorQueries"] = [
                {
                    "kind": "vector",
                    "vector": emb,
                    "fields": "content_vector",
                    "k": 50,
                }
            ]
            mode = "hybrid"

    try:
        import httpx

        url = f"{ep}/indexes/{idx}/docs/search?api-version=2024-07-01"
        with httpx.Client(timeout=25.0) as client:
            r = client.post(
                url,
                headers={"api-key": key, "Content-Type": "application/json"},
                json=body,
            )
        out["http"] = r.status_code
        out["real_query"] = True
        out["search_mode"] = mode if r.status_code == 200 else mode
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            # NUNCA ampliar quitando filtros. Error tipado → caller usa fallback local.
            out["error"] = (
                f"http_{r.status_code}_filter_required"
                if odata
                else f"http_{r.status_code}"
            )
            out["search_mode"] = "error"
            out["filter_stripped"] = False
            return out
        raw_hits = r.json().get("value") or []
        # Budget de evidencia: 3200 chars (compare/condiciones); override env
        try:
            content_budget = int(_env("GENESIS_SEARCH_CONTENT_CHARS", "3200") or "3200")
        except ValueError:
            content_budget = 3200
        content_budget = max(800, min(content_budget, 8000))
        cleaned = []
        for doc in raw_hits:
            title = str(doc.get("title") or "")
            content = str(doc.get("content") or "")
            if _looks_like_matrix_simulation(content, title):
                continue
            cleaned.append(
                {
                    "id": doc.get("id"),
                    "parent_id": doc.get("parent_id"),
                    "title": title[:200],
                    "content": content[:content_budget],
                    "product": doc.get("product"),
                    "document_type": doc.get("document_type"),
                    "functionality": doc.get("functionality"),
                    "intent": doc.get("intent"),
                    "source_row": doc.get("source_row"),
                    "source_file": doc.get("source_file"),
                    "source_scope": doc.get("source_scope"),
                    "score": doc.get("@search.score"),
                    "search_mode": mode,
                }
            )
        rerank_on = _env("GENESIS_SEARCH_RERANK_LOCAL", "1").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if rerank_on:
            ranked = _rerank_hits(
                cleaned, query=query, product_filter=product_filter
            )
            out["reranked"] = True
            out["rerank_kind"] = "local_lexical_bonus"  # NO es Semantic Ranker
        else:
            ranked = cleaned
            out["reranked"] = False
            out["rerank_kind"] = "off"
        out["hits"] = ranked[: max(1, min(int(top), 10))]
        out["discarded_matrix_like"] = max(0, len(raw_hits) - len(cleaned))
        return out
    except Exception as exc:  # noqa: BLE001
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        out["error"] = type(exc).__name__
        out["search_mode"] = "error"
        return out


def best_knowledge_answer(
    query: str,
    *,
    top: int = 5,
    product_filter: str | None = None,
    document_types: list[str] | None = None,
) -> dict[str, Any] | None:
    """Devuelve el mejor hit usable o None. Nunca inventa texto."""
    result = azure_search_retrieve(
        query,
        top=top,
        product_filter=product_filter,
        document_types=document_types,
    )
    if not result.get("real_query"):
        return None
    hits = result.get("hits") or []
    if not hits:
        return {
            "answer": None,
            "meta": result,
            "status": "SEARCH_REAL_NO_HITS",
        }
    hit = hits[0]
    answer = (hit.get("content") or "").strip()
    if not answer:
        return {"answer": None, "meta": result, "status": "SEARCH_REAL_EMPTY"}
    return {
        "answer": answer,
        "title": hit.get("title"),
        "doc_id": hit.get("id"),
        "product": hit.get("product"),
        "score": hit.get("score"),
        "search_mode": result.get("search_mode"),
        "meta": result,
        "status": "SEARCH_REAL_PASS",
    }
