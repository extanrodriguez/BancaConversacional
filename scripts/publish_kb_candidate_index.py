r"""Publica un índice Azure AI Search CANDIDATO limpio (paralelo).

Reglas de seguridad:
  - NUNCA escribe, borra ni recrea `bsc-kb-conocimiento`.
  - Solo crea/actualiza el índice candidato indicado.
  - No modifica `.env` ni el servicio cognitivo; la activación es un paso aparte.

Fuente por defecto:
  data/kb_publish/bsc-kb-2026-09-19-candidate-1/documents.jsonl
  (solo qa_eligible: fichas, glosario/definiciones, procedimientos, institucional)

Uso típico:
  # 1) dry-run (cuenta docs, no toca Azure)
  .\.venv\Scripts\python.exe scripts\publish_kb_candidate_index.py --dry-run

  # 2) crear índice + indexar + validar consultas fijas
  .\.venv\Scripts\python.exe scripts\publish_kb_candidate_index.py ^
      --candidate-index bsc-kb-qa-vnext-20260921 ^
      --create-if-missing --upload --validate

  # 3) solo validar un índice ya poblado
  .\.venv\Scripts\python.exe scripts\publish_kb_candidate_index.py ^
      --candidate-index bsc-kb-qa-vnext-20260921 --validate
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTECTED_INDEX = "bsc-kb-conocimiento"
DEFAULT_BUNDLE = (
    PROJECT_ROOT
    / "data"
    / "kb_publish"
    / "bsc-kb-2026-09-19-candidate-1"
    / "documents.jsonl"
)
API_VERSION = "2024-07-01"

# Consultas fijas de aceptación (sin activar el índice en el servicio)
VALIDATION_QUERIES: list[dict] = [
    {
        "id": "DEF_SALDO",
        "q": "qué significa saldo disponible",
        "must_any": ["disponible", "saldo"],
        "forbid": ["fila ", "datos simulados"],
    },
    {
        "id": "CMP_PLATINUM",
        "q": "visa platinum características",
        "must_any": ["platinum", "platino"],
        "forbid": ["fila ", "infinite"],
    },
    {
        "id": "CMP_INFINITE",
        "q": "visa infinite características",
        "must_any": ["infinite"],
        "forbid": ["fila ", "joven"],
    },
    {
        "id": "CMP_BOTH",
        "q": "comparar visa platinum e infinite",
        "must_any": ["platinum", "infinite", "platino"],
        "forbid": ["fila ", "datos simulados"],
    },
    {
        "id": "PROC_CANCEL",
        "q": "cancelación de productos préstamo",
        "must_any": ["cancel", "préstamo", "prestamo", "producto"],
        "forbid": ["fila ", "saldo actual de tu"],
    },
    {
        "id": "INST_MISION",
        "q": "misión del banco santa cruz",
        "must_any": ["misión", "mision"],
        "forbid": ["fila "],
    },
    {
        "id": "PROC_RECLAMO",
        "q": "proceso de reclamación",
        "must_any": ["reclam"],
        "forbid": ["fila "],
    },
]


def _endpoint() -> str:
    return (os.getenv("AZURE_SEARCH_ENDPOINT") or "").rstrip("/")


def _api_key() -> str:
    key = (os.getenv("AZURE_SEARCH_API_KEY") or "").strip()
    if key:
        return key
    raise SystemExit("Falta AZURE_SEARCH_API_KEY en el entorno/.env")


def _assert_safe_index(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise SystemExit("--candidate-index es obligatorio")
    if n.lower() == PROTECTED_INDEX.lower():
        raise SystemExit(
            f"RECHAZADO: no se permite operar sobre el índice protegido '{PROTECTED_INDEX}'"
        )
    if not re.fullmatch(r"[a-z0-9]([a-z0-9\-]{1,126})", n):
        raise SystemExit(
            f"Nombre de índice inválido '{n}'. Use minúsculas, números y guiones "
            "(ej. bsc-kb-qa-vnext-20260921)."
        )
    return n


def _load_docs(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"Bundle no encontrado: {path}")
    rows: list[dict] = []
    bad = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        title = str(doc.get("title") or "")
        content = str(doc.get("content") or "")
        blob = f"{title}\n{content}".lower()
        if re.search(r"fila\s+\d+", blob) or "datos simulados" in blob:
            bad += 1
            continue
        if doc.get("qa_eligible") is False:
            continue
        kind = str(doc.get("content_kind") or "")
        # Solo conocimiento permitido
        if kind and kind not in {
            "product_knowledge",
            "definition",
            "procedure",
            "scoped_editorial_summary",
            "public_reference",
        }:
            continue
        rows.append(doc)
    print(f"  docs cargados: {len(rows)} (descartados contaminación/matriz: {bad})")
    return rows


def _get_index(ep: str, key: str, name: str) -> dict | None:
    import httpx

    r = httpx.get(
        f"{ep}/indexes/{name}?api-version={API_VERSION}",
        headers={"api-key": key},
        timeout=30.0,
    )
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise SystemExit(f"GET index {name}: {r.status_code} {r.text[:300]}")
    return r.json()


def _clone_schema(source: dict, new_name: str) -> dict:
    """Clona el esquema del índice activo sin secretos redactados.

    El GET de Azure devuelve `apiKey: <redacted>` en vectorizers; eso hace
    fallar el PUT. Como este script ya embebe en cliente, el vectorizer
    integrado no es necesario en el candidato.
    """
    schema = json.loads(json.dumps(source))  # deep copy
    schema["name"] = new_name
    for k in ("@odata.etag", "etag"):
        schema.pop(k, None)
    # encryptionKey / identity ajenas no deben copiarse a ciegas
    schema.pop("encryptionKey", None)

    vs = schema.get("vectorSearch")
    if isinstance(vs, dict):
        # Mantener HNSW + profile; quitar vectorizer (secretos) y su referencia
        vs["vectorizers"] = []
        profiles = []
        for p in vs.get("profiles") or []:
            p2 = dict(p)
            p2.pop("vectorizer", None)
            profiles.append(p2)
        vs["profiles"] = profiles
        schema["vectorSearch"] = vs
    return schema


def _create_index(ep: str, key: str, schema: dict) -> None:
    import httpx

    name = schema["name"]
    r = httpx.put(
        f"{ep}/indexes/{name}?api-version={API_VERSION}",
        headers={"api-key": key, "Content-Type": "application/json"},
        json=schema,
        timeout=60.0,
    )
    if r.status_code not in (200, 201):
        raise SystemExit(f"PUT index {name}: {r.status_code} {r.text[:400]}")
    print(f"  índice creado/actualizado: {name}")


def _detect_vector_field(schema: dict) -> tuple[str, int | None]:
    for f in schema.get("fields") or []:
        if f.get("type") == "Collection(Edm.Single)" and f.get("dimensions"):
            return str(f.get("name") or "content_vector"), int(f["dimensions"])
    for f in schema.get("fields") or []:
        name = str(f.get("name") or "")
        if "vector" in name.lower():
            return name, f.get("dimensions")
    return "content_vector", None


def _openai_client():
    from openai import AzureOpenAI

    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/") + "/"
    version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    if not (api_key and endpoint):
        raise SystemExit("Faltan AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY")
    return AzureOpenAI(azure_endpoint=endpoint, api_version=version, api_key=api_key)


def _embed_batch(client, texts: list[str], deployment: str) -> list[list[float]]:
    resp = client.embeddings.create(model=deployment, input=texts)
    # ordenar por index
    by_i = {d.index: d.embedding for d in resp.data}
    return [list(by_i[i]) for i in range(len(texts))]


def _map_doc_for_foundry(doc: dict, vector: list[float], vector_field: str) -> dict:
    title = str(doc.get("title") or "KB")[:200]
    content = str(doc.get("content") or "")
    kind = str(doc.get("content_kind") or "product_knowledge")
    domain = str(doc.get("domain") or "")
    return {
        "@search.action": "mergeOrUpload",
        "id": str(doc["id"])[:1000],
        "title": title,
        "content": content,
        "embedding_text": content[:4000],
        "document_type": kind,
        "product": domain[:200],
        "parent_id": str(doc.get("parent_id") or "")[:200] or None,
        "source_file": "kb_publish/bsc-kb-2026-09-19-candidate-1",
        "source_section": kind,
        "source_scope": "qa_eligible",
        "status": "candidate",
        "chunk_index": 0,
        vector_field: vector,
    }


def _upload(ep: str, key: str, index: str, docs: list[dict], vector_field: str, dims: int) -> None:
    import httpx

    client = _openai_client()
    deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    print(f"  embedding deployment: {deployment}")

    BATCH = 16
    total = 0
    for i in range(0, len(docs), BATCH):
        batch = docs[i : i + BATCH]
        texts = [str(d.get("content") or d.get("title") or "")[:8000] for d in batch]
        vectors = _embed_batch(client, texts, deployment)
        if dims and len(vectors[0]) != dims:
            raise SystemExit(
                f"dims embedding {len(vectors[0])} != índice {dims}. "
                "Use el mismo AZURE_OPENAI_EMBEDDING_DEPLOYMENT que el índice activo."
            )
        payload = {
            "value": [
                _map_doc_for_foundry(d, v, vector_field)
                for d, v in zip(batch, vectors, strict=True)
            ]
        }
        # Quitar None (algunos esquemas no aceptan null en parent_id)
        for item in payload["value"]:
            for k in list(item.keys()):
                if item[k] is None:
                    del item[k]
        r = httpx.post(
            f"{ep}/indexes/{index}/docs/index?api-version={API_VERSION}",
            headers={"api-key": key, "Content-Type": "application/json"},
            json=payload,
            timeout=120.0,
        )
        if r.status_code >= 400:
            raise SystemExit(f"Upload batch: {r.status_code} {r.text[:400]}")
        total += len(batch)
        print(f"  uploaded {total}/{len(docs)}")
        time.sleep(0.2)
    print(f"  total indexado: {total}")


def _search(ep: str, key: str, index: str, query: str, top: int = 5) -> dict:
    import httpx

    body = {
        "search": query,
        "top": top,
        "count": True,
        "select": "id,title,content,product,document_type,source_scope,status",
        "queryType": "simple",
    }
    r = httpx.post(
        f"{ep}/indexes/{index}/docs/search?api-version={API_VERSION}",
        headers={"api-key": key, "Content-Type": "application/json"},
        json=body,
        timeout=30.0,
    )
    return {"http": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:400]}


def _validate(ep: str, key: str, index: str, out_path: Path) -> bool:
    results = []
    ok_all = True
    for case in VALIDATION_QUERIES:
        res = _search(ep, key, index, case["q"], top=5)
        http = res["http"]
        hits = []
        if http == 200 and isinstance(res["body"], dict):
            hits = res["body"].get("value") or []
        blob = " ".join(
            f"{h.get('title','')} {h.get('content','')}" for h in hits
        ).lower()
        has_must = any(m.lower() in blob for m in case["must_any"]) if hits else False
        has_forbid = any(f.lower() in blob for f in case["forbid"]) if hits else False
        passed = http == 200 and bool(hits) and has_must and not has_forbid
        if not passed:
            ok_all = False
        results.append(
            {
                "id": case["id"],
                "q": case["q"],
                "http": http,
                "n_hits": len(hits),
                "pass": passed,
                "top_titles": [str(h.get("title") or "")[:120] for h in hits[:3]],
            }
        )
        flag = "PASS" if passed else "FAIL"
        print(f"  [{flag}] {case['id']} hits={len(hits)} :: {case['q'][:50]}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "index": index,
        "protected_untouched": PROTECTED_INDEX,
        "all_pass": ok_all,
        "cases": results,
        "utc": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  evidencia: {out_path}")
    return ok_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Publicar índice Search candidato (seguro)")
    parser.add_argument(
        "--candidate-index",
        default="bsc-kb-qa-vnext-20260921",
        help="Nombre del índice NUEVO (nunca bsc-kb-conocimiento)",
    )
    parser.add_argument(
        "--bundle",
        default=str(DEFAULT_BUNDLE),
        help="Ruta a documents.jsonl limpio",
    )
    parser.add_argument(
        "--source-schema-index",
        default=PROTECTED_INDEX,
        help="Índice del que clonar el esquema (solo lectura)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--create-if-missing", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument(
        "--evidence-out",
        default=str(
            PROJECT_ROOT
            / "works"
            / "azure_mejora"
            / "search_candidate_20260921"
            / "validation.json"
        ),
    )
    args = parser.parse_args()

    candidate = _assert_safe_index(args.candidate_index)
    bundle = Path(args.bundle)
    docs = _load_docs(bundle)

    print("=" * 64)
    print("Publish KB candidate index (SAFE)")
    print(f"  endpoint:   {_endpoint() or '(missing)'}")
    print(f"  protected:  {PROTECTED_INDEX} (no write)")
    print(f"  candidate:  {candidate}")
    print(f"  docs:       {len(docs)}")
    print("=" * 64)

    if args.dry_run:
        kinds: dict[str, int] = {}
        for d in docs:
            k = str(d.get("content_kind") or "?")
            kinds[k] = kinds.get(k, 0) + 1
        print("  dry-run OK — kinds:", kinds)
        print("  Siguiente: --create-if-missing --upload --validate")
        return

    if not (args.create_if_missing or args.upload or args.validate):
        raise SystemExit("Indique al menos una acción: --create-if-missing / --upload / --validate")

    ep, key = _endpoint(), _api_key()
    if not ep:
        raise SystemExit("Falta AZURE_SEARCH_ENDPOINT")

    # Lectura del esquema activo (protegido) — solo GET
    src = _get_index(ep, key, args.source_schema_index)
    if src is None:
        raise SystemExit(
            f"No se pudo leer el esquema fuente '{args.source_schema_index}'. "
            "Verifique permisos/API key."
        )
    print(f"  esquema fuente leído: {args.source_schema_index}")

    cand = _get_index(ep, key, candidate)
    if args.create_if_missing:
        if cand is not None:
            print(f"  índice candidato ya existe: {candidate} (no se recrea)")
        else:
            schema = _clone_schema(src, candidate)
            _create_index(ep, key, schema)
            time.sleep(2)
            cand = _get_index(ep, key, candidate)

    if args.upload:
        if cand is None:
            raise SystemExit("Índice candidato no existe. Use --create-if-missing primero.")
        vector_field, dims = _detect_vector_field(cand)
        print(f"  vector_field={vector_field} dims={dims}")
        _upload(ep, key, candidate, docs, vector_field, int(dims or 0))

    if args.validate:
        ok = _validate(ep, key, candidate, Path(args.evidence_out))
        if not ok:
            print("\nVALIDACIÓN INCOMPLETA — no active AZURE_SEARCH_INDEX todavía.")
            sys.exit(2)
        print("\nVALIDACIÓN OK — listo para activación MANUAL en QA:")
        print(f"  1) En la VM, set AZURE_SEARCH_INDEX={candidate}")
        print("  2) Reiniciar SOLO genesis-cognitive-8447")
        print(f"  3) Reversión: AZURE_SEARCH_INDEX={PROTECTED_INDEX}")


if __name__ == "__main__":
    main()
