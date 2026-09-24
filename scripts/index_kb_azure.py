r"""Index Knowledge Base into Azure AI Search — PDF + FAQ JSON + Markdown.

Sources:
  - Knowledge_Base/*.pdf (FAQ embebido + prosa)
  - data/kb_faq_vf01.json + overlay Fase 1
  - Knowledge_Base/excel_vf01/*.md (+ BASE_CONOCIMIENTO_IA_VF01.md)

Auth: AZURE_SEARCH_API_KEY + AzureCliCredential para embeddings
      (o AZURE_OPENAI_API_KEY).

Uso:
    az login
    # opcional en .env:
    # AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_INDEX / AZURE_SEARCH_API_KEY
    # AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_EMBEDDING_DEPLOYMENT

    .\.venv\Scripts\python.exe scripts\index_kb_azure.py --force
    .\.venv\Scripts\python.exe scripts\index_kb_azure.py --force --sources faq,md
    .\.venv\Scripts\python.exe scripts\index_kb_azure.py --force --sources pdf
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

KB_DIR = Path(os.getenv("GENESIS_KB_DIR", str(PROJECT_ROOT / "Knowledge_Base")))
FAQ_PATH = Path(
    os.getenv("GENESIS_FAQ_PATH", str(PROJECT_ROOT / "data" / "kb_faq_vf01.json"))
)
OVERLAY_PATH = Path(
    os.getenv(
        "GENESIS_FAQ_OVERLAY_PATH",
        str(PROJECT_ROOT / "data" / "kb_faq_overlay_fase1.json"),
    )
)
MD_DIR = Path(
    os.getenv(
        "GENESIS_KB_MD_DIR",
        str(KB_DIR / "excel_vf01"),
    )
)

AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://aoai-genesis-871a5b-7e0e0.openai.azure.com/")
EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "https://genesis-search-lab.search.windows.net")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "genesis-kb")

_DISCARD_PHRASES = (
    "Proyecto Genesis", "Documento de trabajo", "Uso interno",
    "No contiene datos reales", "Base de Conocimiento RAG del Asistente",
    "source_type", "document_name", "chunk_id", "domain_category",
    "sensitivity_level", "controlled_operation", "execution_allowed",
    "requires_authentication", "requires_confirmation", "environment",
    "transactional", "Nota de validacion", "Nota de validación",
    "Regla de seguridad aplicable", "Metadatos sugeridos",
    "Pendiente de parametrizacion", "Pendiente de parametrización",
)

_META_LINE_RE = re.compile(
    r"^(Intenci[oó]n|Nivel de sensibilidad|Transaccional|Operaci[oó]n controlada|"
    r"Ejecuci[oó]n permitida|Requiere autenticaci[oó]n|Requiere confirmaci[oó]n|"
    r"Segmento de usuario|Moneda|Prioridad|Chunk_ID|Categor[ií]a|Producto)\s*:"
)


def _stable_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get_search_key() -> str:
    key = os.getenv("AZURE_SEARCH_API_KEY", "")
    if key:
        return key
    import subprocess
    result = subprocess.run(
        "az search admin-key show --service-name genesis-search-lab "
        "--resource-group rg-genesis-cognitive-mvp-eus -o json",
        capture_output=True, text=True, timeout=30, shell=True,
    )
    if result.returncode != 0:
        print(f"ERROR: {result.stderr[:200]}")
        sys.exit(1)
    return json.loads(result.stdout)["primaryKey"]


def get_openai_client():
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    from openai import AzureOpenAI
    if api_key:
        return AzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            api_version=AZURE_API_VERSION,
            api_key=api_key,
        )
    from azure.identity import AzureCliCredential
    credential = AzureCliCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    return AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_version=AZURE_API_VERSION,
        azure_ad_token=token.token,
    )


def _should_discard_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if any(p in stripped for p in _DISCARD_PHRASES):
        return True
    if _META_LINE_RE.match(stripped):
        return True
    if stripped.startswith("{") and "source_type" in stripped:
        return True
    if stripped.startswith('"') and '":' in stripped:
        return True
    return False


def extract_faq_documents(pdf_path: Path) -> list[dict]:
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    documents: list[dict] = []
    current_faq_id: str | None = None
    current_question: str | None = None
    current_answer_lines: list[str] = []
    current_page = 0
    current_product: str | None = None

    def _flush():
        nonlocal current_faq_id, current_question, current_answer_lines, current_product
        if current_question and current_answer_lines:
            answer = " ".join(current_answer_lines).strip()
            if len(answer) > 30:
                content = f"Pregunta: {current_question}\nRespuesta: {answer}"
                documents.append({
                    "id": str(uuid.uuid4()).replace("-", ""),
                    "content": content,
                    "source_file": pdf_path.name,
                    "page": current_page,
                    "faq_id": current_faq_id or "",
                    "product_type": current_product or "",
                })
        current_faq_id = None
        current_question = None
        current_answer_lines = []
        current_product = None

    for page_idx, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if not text.strip():
            continue
        current_page = page_idx + 1
        for line in text.split("\n"):
            stripped = line.strip()
            faq_match = re.match(r"^FAQ-(\d+)", stripped)
            if faq_match:
                _flush()
                current_faq_id = f"FAQ-{faq_match.group(1)}"
                continue
            prod_match = re.match(r"^Producto\s*:\s*(.+)", stripped)
            if prod_match:
                current_product = prod_match.group(1).strip()
                continue
            q_match = re.match(r"^Pregunta\s+t[ií]pica\s*:\s*(.+)", stripped)
            if q_match:
                if current_question:
                    _flush()
                current_question = q_match.group(1).strip()
                continue
            a_match = re.match(r"^Respuesta(?:\s+RAG)?\s*:\s*(.+)", stripped)
            if a_match:
                current_answer_lines = [a_match.group(1).strip()]
                continue
            if current_question and current_answer_lines:
                if not _should_discard_line(line):
                    current_answer_lines.append(stripped)
    _flush()
    return documents


def extract_prose_chunks(pdf_path: Path) -> list[dict]:
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    chunks: list[dict] = []
    for page_idx, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if not text.strip():
            continue
        lines = text.split("\n")
        clean_lines = [l.strip() for l in lines if l.strip() and not _should_discard_line(l)]
        paragraph = " ".join(clean_lines)
        if len(paragraph) < 80:
            continue
        CHUNK, OVERLAP = 2000, 200
        start = 0
        while start < len(paragraph):
            chunk_text = paragraph[start:start + CHUNK].strip()
            if len(chunk_text) >= 80:
                chunks.append({
                    "id": str(uuid.uuid4()).replace("-", ""),
                    "content": chunk_text,
                    "source_file": pdf_path.name,
                    "page": page_idx + 1,
                    "faq_id": "",
                    "product_type": "",
                })
            start += CHUNK - OVERLAP
    return chunks


def extract_faq_json_documents() -> list[dict]:
    by_id: dict[str, dict] = {}

    def _ingest(path: Path, label: str) -> None:
        if not path.is_file():
            print(f"  (skip {label}: no existe {path})")
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        n = 0
        for e in data.get("entries") or []:
            eid = str(e.get("id") or "")
            ans = (e.get("answer") or "").strip()
            topic = (e.get("topic") or "").strip()
            product = (e.get("product") or "").strip()
            exprs = list(e.get("expressions") or []) + list(e.get("synonyms") or [])
            if eid and eid in by_id:
                cur = by_id[eid]
                if ans and len(ans) > len(cur.get("_answer") or ""):
                    cur["_answer"] = ans
                cur["_exprs"] = list(dict.fromkeys(cur.get("_exprs", []) + exprs))
                if topic:
                    cur["_topic"] = topic
                if product:
                    cur["_product"] = product
                continue
            if len(ans) < 40:
                continue
            low = ans.lower()
            if "basada exclusivamente" in low or "[respuesta" in low:
                continue
            if low.startswith("tema de informacion") or low.startswith("tema de información"):
                continue
            item = {
                "_answer": ans,
                "_exprs": exprs,
                "_topic": topic,
                "_product": product,
                "_id": eid or _stable_id(label, topic, ans[:80]),
                "_source": path.name,
            }
            by_id[item["_id"]] = item
            n += 1
        print(f"  FAQ JSON {label}: +{n} ({path.name})")

    _ingest(FAQ_PATH, "base")
    _ingest(OVERLAY_PATH, "overlay")

    entries: list[dict] = []
    for item in by_id.values():
        ans = item["_answer"]
        topic = item["_topic"]
        exprs = item["_exprs"][:12]
        q_block = "\n".join(f"- {x}" for x in exprs) if exprs else f"- {topic}"
        content = (
            f"Tema: {topic}\n"
            f"Producto: {item['_product']}\n"
            f"Preguntas ejemplo:\n{q_block}\n\n"
            f"Respuesta:\n{ans}"
        ).strip()
        entries.append({
            "id": _stable_id("faqjson", item["_id"]),
            "content": content[:8000],
            "source_file": item["_source"],
            "page": 0,
            "faq_id": item["_id"][:120],
            "product_type": item["_product"][:120],
        })
    return entries


def extract_markdown_documents() -> list[dict]:
    docs: list[dict] = []
    md_files: list[Path] = []
    if MD_DIR.is_dir():
        md_files.extend(sorted(MD_DIR.glob("*.md")))
    root_md = KB_DIR / "BASE_CONOCIMIENTO_IA_VF01.md"
    if root_md.is_file():
        md_files.append(root_md)

    for md in md_files:
        try:
            body = md.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"  skip {md.name}: {exc}")
            continue
        parts = re.split(r"(?m)^##\s+", body)
        if len(parts) <= 1:
            clean = "\n".join(
                ln for ln in body.splitlines() if not _should_discard_line(ln)
            ).strip()
            CHUNK, OVERLAP = 2000, 200
            start = 0
            i = 0
            while start < len(clean):
                chunk = clean[start:start + CHUNK].strip()
                if len(chunk) >= 80:
                    i += 1
                    docs.append({
                        "id": _stable_id("md", md.name, str(i)),
                        "content": chunk,
                        "source_file": md.name,
                        "page": i,
                        "faq_id": "",
                        "product_type": md.stem[:120],
                    })
                start += CHUNK - OVERLAP
            continue

        product = md.stem.replace("_", " ")
        for chunk in parts[1:]:
            lines = chunk.strip().splitlines()
            if not lines:
                continue
            topic = lines[0].strip()
            answer_lines = [ln for ln in lines[1:] if not _should_discard_line(ln)]
            answer = "\n".join(answer_lines).strip()
            if len(answer) < 40:
                continue
            content = (
                f"Tema: {topic}\nProducto: {product}\n"
                f"Preguntas ejemplo:\n- qué es {topic}\n- {topic}\n\n"
                f"Respuesta:\n{answer}"
            )
            docs.append({
                "id": _stable_id("md", md.name, topic),
                "content": content[:8000],
                "source_file": md.name,
                "page": 0,
                "faq_id": topic[:120],
                "product_type": product[:120],
            })
    print(f"  Markdown sections: {len(docs)} from {len(md_files)} files")
    return docs


def embed_chunks(oai_client, chunks: list[dict]) -> list[dict]:
    import time
    BATCH = 16
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        texts = [c["content"] for c in batch]
        for attempt in range(3):
            try:
                resp = oai_client.embeddings.create(input=texts, model=EMBEDDING_DEPLOYMENT)
                for j, emb in enumerate(resp.data):
                    batch[j]["content_vector"] = emb.embedding
                print(f"  Embedded batch {i // BATCH + 1} ({len(batch)} chunks)")
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  Retry batch {i // BATCH + 1}: {str(e)[:60]}")
                    time.sleep(3)
                else:
                    raise
        time.sleep(0.5)
    return chunks


def delete_index(search_key: str) -> None:
    import httpx
    r = httpx.delete(
        f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}?api-version=2024-07-01",
        headers={"api-key": search_key},
        timeout=15.0,
    )
    if r.status_code in (204, 404):
        print("  Index deleted (or didn't exist)")
    else:
        print(f"  Delete failed: {r.status_code}")


def index_exists(search_key: str) -> bool:
    import httpx
    r = httpx.get(
        f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}?api-version=2024-07-01",
        headers={"api-key": search_key},
        timeout=15.0,
    )
    return r.status_code == 200


def create_index(search_key: str, vector_dims: int) -> None:
    import httpx
    schema = {
        "name": SEARCH_INDEX,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "source_file", "type": "Edm.String", "filterable": True, "searchable": False},
            {"name": "page", "type": "Edm.Int32", "filterable": True, "searchable": False},
            {"name": "faq_id", "type": "Edm.String", "filterable": True, "searchable": False},
            {"name": "product_type", "type": "Edm.String", "filterable": True, "searchable": False},
            {
                "name": "content_vector",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "dimensions": vector_dims,
                "vectorSearchProfile": "default-profile",
            },
        ],
        "vectorSearch": {
            "algorithms": [{"name": "hnsw-algo", "kind": "hnsw"}],
            "profiles": [{"name": "default-profile", "algorithm": "hnsw-algo"}],
        },
    }
    r = httpx.put(
        f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}?api-version=2024-07-01",
        headers={"api-key": search_key, "Content-Type": "application/json"},
        json=schema,
        timeout=30.0,
    )
    if r.status_code in (200, 201):
        print(f"  Index created ({vector_dims} dims)")
    else:
        print(f"  Index create failed: {r.status_code} {r.text[:200]}")
        sys.exit(1)


def detect_vector_field(search_key: str) -> tuple[str, int | None]:
    """Devuelve (nombre_campo_vector, dims) del índice existente."""
    import httpx
    r = httpx.get(
        f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}?api-version=2024-07-01",
        headers={"api-key": search_key},
        timeout=15.0,
    )
    if r.status_code != 200:
        return "content_vector", None
    data = r.json()
    for f in data.get("fields") or []:
        if f.get("type") == "Collection(Edm.Single)" and f.get("dimensions"):
            return str(f.get("name") or "content_vector"), int(f["dimensions"])
    # fallback: primer campo *vector*
    for f in data.get("fields") or []:
        name = str(f.get("name") or "")
        if "vector" in name.lower():
            return name, f.get("dimensions")
    return "content_vector", None


def upload_documents(
    search_key: str,
    chunks: list[dict],
    *,
    vector_field: str = "content_vector",
    existing_schema: bool = False,
) -> None:
    import httpx
    BATCH = 50
    total = 0
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        docs = []
        for c in batch:
            if existing_schema:
                # Schema real de bsc-kb-conocimiento (Foundry)
                title = (c.get("faq_id") or c.get("product_type") or "KB")[:200]
                docs.append({
                    "@search.action": "mergeOrUpload",
                    "id": c["id"],
                    "title": title,
                    "content": c["content"],
                    "embedding_text": c["content"][:4000],
                    "document_type": "faq_md",
                    "product": (c.get("product_type") or "")[:200],
                    "source_file": c.get("source_file") or "",
                    "source_section": (c.get("faq_id") or "")[:200],
                    "chunk_index": int(c.get("page") or 0),
                    vector_field: c["content_vector"],
                })
            else:
                docs.append({
                    "@search.action": "mergeOrUpload",
                    "id": c["id"],
                    "content": c["content"],
                    "source_file": c.get("source_file") or "",
                    "page": int(c.get("page") or 0),
                    "faq_id": c.get("faq_id") or "",
                    "product_type": c.get("product_type") or "",
                    vector_field: c["content_vector"],
                })
        r = httpx.post(
            f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/index?api-version=2024-07-01",
            headers={"api-key": search_key, "Content-Type": "application/json"},
            json={"value": docs},
            timeout=60.0,
        )
        if r.status_code >= 400:
            print(f"  Upload batch failed: {r.status_code} {r.text[:300]}")
            sys.exit(1)
        total += len(batch)
        print(f"  Uploaded {total}/{len(chunks)}")
    print(f"  Total: {total}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Borra y recrea el índice")
    parser.add_argument(
        "--sources",
        default="faq,md,pdf",
        help="Comma list: faq,md,pdf (default: all)",
    )
    args = parser.parse_args()
    sources = {s.strip().lower() for s in args.sources.split(",") if s.strip()}

    print("=" * 60)
    print("Genesis KB → Azure AI Search (FAQ JSON + MD + PDF)")
    print(f"  endpoint: {SEARCH_ENDPOINT}")
    print(f"  index:    {SEARCH_INDEX}")
    print(f"  sources:  {sorted(sources)}")
    print("=" * 60)

    search_key = get_search_key()
    oai_client = get_openai_client()
    print("  Auth OK")

    all_docs: list[dict] = []

    if "faq" in sources:
        print("\n[FAQ JSON]")
        all_docs.extend(extract_faq_json_documents())

    if "md" in sources:
        print("\n[Markdown]")
        all_docs.extend(extract_markdown_documents())

    if "pdf" in sources:
        print("\n[PDF]")
        pdfs = list(KB_DIR.glob("*.pdf"))
        if not pdfs:
            print("  (no PDFs in Knowledge_Base)")
        for pdf in pdfs:
            print(f"  Processing: {pdf.name}")
            faqs = extract_faq_documents(pdf)
            prose = extract_prose_chunks(pdf)
            print(f"    FAQ docs: {len(faqs)}, Prose chunks: {len(prose)}")
            all_docs.extend(faqs)
            all_docs.extend(prose)

    dedup: dict[str, dict] = {}
    for d in all_docs:
        dedup[d["id"]] = d
    all_docs = list(dedup.values())

    print(f"\n  Total clean documents: {len(all_docs)}")
    if not all_docs:
        print("ERROR: No documents extracted")
        sys.exit(1)

    print("\n  Sample documents:")
    for d in all_docs[:3]:
        print(f"    [{d.get('faq_id') or 'prose'}] {d['content'][:80]}...")

    print("\n  Embedding...")
    all_docs = embed_chunks(oai_client, all_docs)
    dims = len(all_docs[0]["content_vector"])

    exists = index_exists(search_key)
    vector_field = "content_vector"
    existing_schema = False

    if args.force:
        print("\n  Deleting old index...")
        delete_index(search_key)
        import time
        time.sleep(2)
        print("  Creating index...")
        create_index(search_key, dims)
        exists = False
    elif exists:
        vector_field, idx_dims = detect_vector_field(search_key)
        print(f"  Índice existente: vector_field={vector_field} dims={idx_dims}")
        if idx_dims and idx_dims != dims:
            print(
                f"ERROR: dims del embedding ({dims}) != dims del índice ({idx_dims}). "
                "Usa el mismo modelo de embedding o --force (borra el índice)."
            )
            sys.exit(1)
        existing_schema = True
        print("  Omitiendo create schema (índice Foundry ya definido).")
    else:
        print("  Creating index...")
        create_index(search_key, dims)

    print("  Uploading...")
    upload_documents(
        search_key,
        all_docs,
        vector_field=vector_field,
        existing_schema=existing_schema,
    )
    print(f"\n  Done. {len(all_docs)} documents indexed into '{SEARCH_INDEX}'.")
    print("  Foundry / local_rag usarán este índice si AZURE_SEARCH_INDEX coincide.")


if __name__ == "__main__":
    main()
