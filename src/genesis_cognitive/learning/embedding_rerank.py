"""Rerank FAQ por embeddings (capa 2 del modelo de aprendizaje).

Usa Azure OpenAI embeddings si hay credenciales; si no, no-op.
No entrena una red desde cero: reutiliza text-embedding-3-small del stack.
"""

from __future__ import annotations

import math
import os
from typing import Any


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embeddings vía Azure OpenAI; None si no configurado."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small").strip()
    if not endpoint or not key or not texts:
        return None
    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            api_key=key,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            azure_endpoint=endpoint,
        )
        resp = client.embeddings.create(model=deployment, input=texts)
        return [list(d.embedding) for d in resp.data]
    except Exception:
        return None


def rerank_faq_entries(
    question: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int = 3,
) -> list[tuple[float, dict[str, Any]]]:
    """Ordena candidatos FAQ por similitud semántica pregunta↔(topic+answer)."""
    if not question.strip() or not candidates:
        return []
    docs = [
        f"{c.get('topic') or ''}\n{c.get('answer') or ''}"[:2000]
        for c in candidates
    ]
    vectors = embed_texts([question] + docs)
    if not vectors or len(vectors) != len(docs) + 1:
        return [(0.0, c) for c in candidates[:top_k]]
    qv = vectors[0]
    scored = [(_cosine(qv, vectors[i + 1]), candidates[i]) for i in range(len(candidates))]
    scored.sort(key=lambda x: -x[0])
    return scored[:top_k]
