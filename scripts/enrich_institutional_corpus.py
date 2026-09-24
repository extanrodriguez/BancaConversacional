#!/usr/bin/env python3
"""Recuperación P0: enriquece candidato con institucional VF01 (misión/visión).

Solo texto aprobado de Knowledge_Base/BASE_CONOCIMIENTO_IA_VF01.md (Filas 81/83).
No toca bsc-kb-conocimiento. No inventa contenido.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import httpx
from openai import AzureOpenAI

ROOT = Path(__file__).resolve().parents[1]
INDEX = "bsc-kb-qa-vnext-20260921"
PROTECTED = "bsc-kb-conocimiento"
API = "2024-07-01"
OUT = ROOT / "works" / "recuperacion_integral" / "institutional_docs.jsonl"

MISION_ANSWER = (
    "Somos una institución financiera orientada a empresas e individuos emprendedores. "
    "Satisfacemos las necesidades financieras de nuestros clientes, acompañándoles a "
    "crecer a través de una relación personalizada, ofreciendo productos y servicios "
    "creados a su medida y entregados con un estilo de servicio único, oportuno y "
    "excepcional, agregando valor a su negocio y mejorando su calidad de vida. "
    "Ofrecemos una inversión segura y rentable a nuestros accionistas. Promovemos el "
    "desarrollo de nuestros colaboradores y de nuestra comunidad."
)
MISION_EMBED = (
    "Misión del Banco Santa Cruz. ¿Cuál es la misión del Banco? "
    "Cuéntame sobre la misión de Banco Santa Cruz. misión del banco. "
    f"{MISION_ANSWER}"
)

VISION_ANSWER = (
    "Ser el Banco preferido de nuestros clientes, ofreciendo un servicio conveniente, "
    "transparente, simple, con un equipo de personas capaces y motivadas a ofrecer un "
    "beneficio tangible."
)
VISION_EMBED = (
    "Visión del Banco Santa Cruz. ¿Cuál es la visión del Banco? "
    "Cuéntame sobre la visión de Banco Santa Cruz. visión del banco. "
    f"{VISION_ANSWER}"
)


def build_docs() -> list[dict]:
    return [
        {
            "id": "inst-vf01-mision-bsc",
            "title": "Misión — Banco Santa Cruz",
            "content": f"Misión del Banco Santa Cruz. {MISION_ANSWER}",
            "embedding_text": MISION_EMBED,
            "content_kind": "definition",
            "domain": "institucional",
            "qa_eligible": True,
            "source_file": "Knowledge_Base/BASE_CONOCIMIENTO_IA_VF01.md",
            "source_section": "Fila 81 — Misión",
        },
        {
            "id": "inst-vf01-vision-bsc",
            "title": "Visión — Banco Santa Cruz",
            "content": f"Visión del Banco Santa Cruz. {VISION_ANSWER}",
            "embedding_text": VISION_EMBED,
            "content_kind": "definition",
            "domain": "institucional",
            "qa_eligible": True,
            "source_file": "Knowledge_Base/BASE_CONOCIMIENTO_IA_VF01.md",
            "source_section": "Fila 83 — Visión",
        },
        {
            "id": "inst-vf01-mision-vision-combo",
            "title": "Misión y Visión — Banco Santa Cruz",
            "content": (
                f"Misión del Banco Santa Cruz. {MISION_ANSWER}\n\n"
                f"Visión del Banco Santa Cruz. {VISION_ANSWER}"
            ),
            "embedding_text": f"{MISION_EMBED} {VISION_EMBED}",
            "content_kind": "definition",
            "domain": "institucional",
            "qa_eligible": True,
            "source_file": "Knowledge_Base/BASE_CONOCIMIENTO_IA_VF01.md",
            "source_section": "Filas 81 y 83",
        },
    ]


def embed_batch(client: AzureOpenAI, texts: list[str], deployment: str) -> list[list[float]]:
    resp = client.embeddings.create(model=deployment, input=texts)
    by_i = {d.index: d.embedding for d in resp.data}
    return [list(by_i[i]) for i in range(len(texts))]


def upload(docs: list[dict]) -> None:
    if INDEX.lower() == PROTECTED.lower():
        raise SystemExit("RECHAZADO: no escribir en índice protegido")
    ep = (os.getenv("AZURE_SEARCH_ENDPOINT") or "").rstrip("/")
    key = os.getenv("AZURE_SEARCH_API_KEY") or ""
    if not (ep and key):
        raise SystemExit("Falta Search endpoint/key")
    oai = AzureOpenAI(
        azure_endpoint=(os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/") + "/",
        api_key=os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    )
    emb_dep = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    vectors = embed_batch(
        oai, [d.get("embedding_text") or d["content"][:8000] for d in docs], emb_dep
    )
    payload = {"value": []}
    for d, vec in zip(docs, vectors, strict=True):
        emb_txt = d.get("embedding_text") or d["content"]
        payload["value"].append(
            {
                "@search.action": "mergeOrUpload",
                "id": d["id"],
                "title": d["title"][:200],
                "content": d["content"],
                "embedding_text": emb_txt[:4000],
                "document_type": d["content_kind"],
                "product": d.get("domain") or "institucional",
                "source_file": d.get("source_file") or "",
                "source_section": d.get("source_section") or "",
                "source_scope": "qa_eligible_institutional",
                "status": "candidate",
                "chunk_index": 0,
                "content_vector": vec,
            }
        )
    r = httpx.post(
        f"{ep}/indexes/{INDEX}/docs/index?api-version={API}",
        headers={"api-key": key, "Content-Type": "application/json"},
        json=payload,
        timeout=120.0,
    )
    if r.status_code >= 400:
        raise SystemExit(f"upload fail {r.status_code} {r.text[:400]}")
    print("uploaded", len(docs))
    time.sleep(0.5)
    st = httpx.get(
        f"{ep}/indexes/{INDEX}/stats?api-version={API}",
        headers={"api-key": key},
        timeout=30,
    ).json()
    print("index docs now:", st.get("documentCount"))


def main() -> int:
    docs = build_docs()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(docs)} -> {OUT}")
    upload(docs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
