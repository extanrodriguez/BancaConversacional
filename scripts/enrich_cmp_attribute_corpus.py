#!/usr/bin/env python3
"""Incremento C: enriquece índice candidato con atributos CMP desde VF01.

NO inventa tasas numéricas por producto. Usa solo texto de Knowledge_Base/excel_vf01.
Sube documentos adicionales a bsc-kb-qa-vnext-20260921 (mergeOrUpload).
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
OUT = ROOT / "works" / "mejora_supervisada" / "incremento_c" / "attribute_docs.jsonl"


def build_docs() -> list[dict]:
    """Documentos atributo derivados de Tarjeta_de_Crédito.md (VF01)."""
    docs: list[dict] = []

    # Requisitos generales TCC (aplican a contratación tarjetas de crédito)
    req = (
        "Requisitos y prerrequisitos de la contratación del producto Tarjeta de Crédito "
        "(Visa Clásica, Gold, Platinum, Infinite, Joven y demás TCC del catálogo, "
        "salvo que una ficha indique requisitos específicos distintos): "
        "Información de la Cédula de Identidad y Electoral. "
        "Mínimo 6 (seis) meses en trabajo actual y 12 (doce) meses en caso de haber "
        "tenido empleo anterior. Si el domicilio es alquilado, el monto de la renta no "
        "deberá ser más de veintidós (22%) del salario. Certificación de ingresos. "
        "Edad entre 18 y 70 años."
    )
    for prod, label in [
        ("visa_clasica", "Visa Clásica"),
        ("visa_gold", "Visa Gold"),
        ("visa_platinum", "Visa Platinum"),
        ("visa_infinite", "Visa Infinite"),
        ("visa_joven", "Visa Joven"),
    ]:
        docs.append(
            {
                "id": f"cmp-attr-req-{prod}",
                "title": f"Requisitos Tarjeta de Crédito {label}",
                "content": req,
                "content_kind": "product_knowledge",
                "domain": "tarjetas",
                "qa_eligible": True,
                "attribute": "requirement",
                "product_ref": prod,
                "source_file": "Knowledge_Base/excel_vf01/Tarjeta_de_Crédito.md",
                "source_section": "Requisitos y prerrequisitos",
            }
        )

    # Beneficios: Puntos (con productos participantes) + cashback genérico
    puntos = (
        "Beneficio — Puntos Santa Cruz: el Programa de Lealtad Puntos Santa Cruz permite "
        "a los tarjetahabientes acumular puntos por consumos con las tarjetas de crédito "
        "participantes (Clásica, Gold, Platinum, Infinite, Empresarial, Full Car Personal "
        "y Full Car Empresarial). Estos puntos pueden canjearse por servicios turísticos, "
        "alquileres, seguros, ofertas especiales o créditos al balance de la tarjeta. "
        "Exclusión: no participan las tarjetas de débito ni transacciones como avances "
        "de efectivo, cargos, seguros o consumos no autorizados."
    )
    for prod, label in [
        ("visa_clasica", "Visa Clásica"),
        ("visa_gold", "Visa Gold"),
        ("visa_platinum", "Visa Platinum"),
        ("visa_infinite", "Visa Infinite"),
    ]:
        docs.append(
            {
                "id": f"cmp-attr-benefit-puntos-{prod}",
                "title": f"Beneficios Puntos Santa Cruz — {label}",
                "content": f"Tarjeta de Crédito {label}. {puntos}",
                "content_kind": "product_knowledge",
                "domain": "tarjetas",
                "qa_eligible": True,
                "attribute": "benefit",
                "product_ref": prod,
                "source_file": "Knowledge_Base/excel_vf01/Tarjeta_de_Crédito.md",
                "source_section": "Puntos Santa Cruz",
            }
        )

    # Exclusiones de recompensas (débito / avances)
    excl = (
        "Exclusión del programa Puntos Santa Cruz: no participan las tarjetas de débito "
        "ni las transacciones como avances de efectivo, cargos, seguros o consumos no "
        "autorizados. La participación, categorías y vencimientos deben consultarse en "
        "las condiciones vigentes del programa."
    )
    for prod, label in [
        ("visa_platinum", "Visa Platinum"),
        ("visa_infinite", "Visa Infinite"),
        ("visa_gold", "Visa Gold"),
        ("visa_joven", "Visa Joven"),
    ]:
        docs.append(
            {
                "id": f"cmp-attr-excl-{prod}",
                "title": f"Exclusiones recompensas — {label}",
                "content": f"Respecto de Tarjeta de Crédito {label}: {excl}",
                "content_kind": "product_knowledge",
                "domain": "tarjetas",
                "qa_eligible": True,
                "attribute": "exclusion",
                "product_ref": prod,
                "source_file": "Knowledge_Base/excel_vf01/Tarjeta_de_Crédito.md",
                "source_section": "Puntos Santa Cruz / exclusiones",
            }
        )

    # Tasa: metodología aprobada (sin inventar % por producto) + remisión a tarifario
    tasa = (
        "Tasa de interés / metodología Tarjeta de Crédito: el interés por financiamiento "
        "(IF) se genera cuando el cliente no realiza el pago total del balance del estado "
        "de cuenta a la fecha de corte, antes o en la fecha límite de pago. Se calcula "
        "sobre el saldo insoluto promedio diario de capital (SPDK), excluyendo consumos "
        "posteriores a la fecha de corte, intereses, comisiones y otros cargos, con "
        "IF = SPDK x i/12, donde i es la tasa de interés anual (TIN) resultante de sumar "
        "la tasa de interés de referencia. Los intereses calculados se cargan al balance "
        "en la fecha de corte. "
        "La tasa numérica vigente por moneda (pesos/dólares) y producto se consulta en el "
        "tarifario oficial publicado por Banco Santa Cruz; no se inventan porcentajes aquí. "
        "Aplica al catálogo de Tarjetas de Crédito (incluye Clásica, Gold, Platinum, "
        "Infinite y Joven) salvo condiciones contractuales específicas del producto."
    )
    for prod, label in [
        ("visa_clasica", "Visa Clásica"),
        ("visa_gold", "Visa Gold"),
        ("visa_platinum", "Visa Platinum"),
        ("visa_infinite", "Visa Infinite"),
        ("visa_joven", "Visa Joven"),
    ]:
        docs.append(
            {
                "id": f"cmp-attr-rate-{prod}",
                "title": f"Tasa de interés financiamiento — {label}",
                "content": f"Tarjeta de Crédito {label}. {tasa}",
                "content_kind": "product_knowledge",
                "domain": "tarjetas",
                "qa_eligible": True,
                "attribute": "rate",
                "product_ref": prod,
                "source_file": "Knowledge_Base/excel_vf01/Tarjeta_de_Crédito.md",
                "source_section": "Metodología tasa / tarifario",
            }
        )

    # Features enriquecidas (texto VF01 + marcadores features)
    features = {
        "visa_platinum": (
            "Tarjeta de Crédito Visa Platinum: instrumento de pago que permite realizar "
            "pagos o consumos en establecimientos afiliados sin efectivo, con características "
            "y condiciones de uso de tarjetas Platinum y beneficios exclusivos documentados "
            "en el catálogo. Detalle adicional en el sitio web de Tarjetas de Crédito."
        ),
        "visa_infinite": (
            "Tarjeta de Crédito Visa Infinite: diseñada para satisfacer requisitos y "
            "necesidades de un segmento selecto; permite pagos y consumos con características "
            "propias de Infinite. Condiciones y beneficios según ficha y sitio web de "
            "Tarjetas de Crédito."
        ),
        "visa_gold": (
            "Tarjeta de Crédito Visa Gold: permite simplificar pagos de forma segura y "
            "flexible, con características de respaldar necesidades de manera confiable. "
            "Detalle en el sitio web de Tarjetas de Crédito."
        ),
        "visa_joven": (
            "Tarjeta de Crédito Visa Joven: diseñada para el subsegmento joven; permite "
            "desarrollar historial crediticio e independencia económica, con características "
            "propias del producto Joven. Detalle en el sitio web de Tarjetas de Crédito."
        ),
        "visa_clasica": (
            "Tarjeta de Crédito Visa Clásica: permite simplificar pagos de forma segura y "
            "flexible, con características de respaldar necesidades de manera confiable. "
            "Detalle en el sitio web de Tarjetas de Crédito."
        ),
    }
    for prod, text in features.items():
        label = prod.replace("visa_", "Visa ").title().replace("Clasica", "Clásica")
        docs.append(
            {
                "id": f"cmp-attr-features-{prod}",
                "title": f"Características {label}",
                "content": text,
                "content_kind": "product_knowledge",
                "domain": "tarjetas",
                "qa_eligible": True,
                "attribute": "features",
                "product_ref": prod,
                "source_file": "Knowledge_Base/excel_vf01/Tarjeta_de_Crédito.md",
                "source_section": "ficha producto",
            }
        )

    return docs


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

    BATCH = 12
    total = 0
    for i in range(0, len(docs), BATCH):
        batch = docs[i : i + BATCH]
        vectors = embed_batch(oai, [d["content"][:8000] for d in batch], emb_dep)
        payload = {"value": []}
        for d, vec in zip(batch, vectors, strict=True):
            payload["value"].append(
                {
                    "@search.action": "mergeOrUpload",
                    "id": d["id"],
                    "title": d["title"][:200],
                    "content": d["content"],
                    "embedding_text": d["content"][:4000],
                    "document_type": d["content_kind"],
                    "product": d.get("domain") or "tarjetas",
                    "source_file": d.get("source_file") or "",
                    "source_section": d.get("attribute") or "",
                    "source_scope": "qa_eligible_attr",
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
        total += len(batch)
        print(f"uploaded {total}/{len(docs)}")
        time.sleep(0.15)
    print("done", total)


def main() -> int:
    docs = build_docs()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(docs)} docs -> {OUT}")
    upload(docs)
    # stats
    ep = (os.getenv("AZURE_SEARCH_ENDPOINT") or "").rstrip("/")
    key = os.getenv("AZURE_SEARCH_API_KEY") or ""
    st = httpx.get(
        f"{ep}/indexes/{INDEX}/stats?api-version={API}",
        headers={"api-key": key},
        timeout=30,
    ).json()
    print("index docs now:", st.get("documentCount"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
