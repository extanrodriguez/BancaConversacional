r"""Index Knowledge Base PDFs into Chroma vector store for RAG.

Usage:
    .\.venv\Scripts\python.exe scripts/index_kb_rag.py

Idempotent: skips if collection already has documents (use --force to reindex).
Requires: chromadb, pypdf, openai (Azure embedding deployment).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

KB_DIR = Path(os.getenv("GENESIS_KB_DIR", str(PROJECT_ROOT / "Knowledge_Base")))
CHROMA_DIR = Path(os.getenv("GENESIS_CHROMA_DIR", str(PROJECT_ROOT / "data" / "rag" / "chroma")))
COLLECTION_NAME = "genesis_kb"
CHUNK_SIZE = 600  # tokens approx (chars / 4)
CHUNK_OVERLAP = 100
EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://aoai-genesis-871a5b-7e0e0.openai.azure.com/")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")


def extract_text_from_pdf(pdf_path: Path) -> list[dict]:
    """Extract text pages from PDF. Returns [{page, text, source}]."""
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({"page": i + 1, "text": text.strip(), "source": pdf_path.name})
    return pages


def chunk_pages(pages: list[dict], chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """Split pages into overlapping chunks (~chunk_size chars)."""
    chunks = []
    for page_data in pages:
        text = page_data["text"]
        # Approximate token-based chunking using chars (4 chars ~ 1 token)
        char_size = chunk_size * 4
        char_overlap = overlap * 4
        start = 0
        while start < len(text):
            end = start + char_size
            chunk_text = text[start:end]
            if chunk_text.strip():
                chunks.append({
                    "text": chunk_text.strip(),
                    "source": page_data["source"],
                    "page": page_data["page"],
                    "chunk_start": start,
                })
            start += char_size - char_overlap
    return chunks


def get_embedding_function():
    """Create embedding function for Chroma.

    Strategy:
    1. Try Azure OpenAI embedding (same resource/auth as inspector chat).
    2. If deployment not found (404): fall back to Chroma default embeddings (local).
    3. If auth fails (401): raise with clear message.

    Auth: AzureCliCredential (same as inspector chat client).
    """
    from chromadb import EmbeddingFunction, Documents, Embeddings

    # Try Azure first
    try:
        from azure.identity import AzureCliCredential
        from openai import AzureOpenAI

        credential = AzureCliCredential()
        token = credential.get_token("https://cognitiveservices.azure.com/.default")

        client = AzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            api_version=AZURE_API_VERSION,
            azure_ad_token=token.token,
        )

        # Test with a tiny call
        test_resp = client.embeddings.create(input=["test"], model=EMBEDDING_DEPLOYMENT)
        if test_resp.data:
            print(f"  Using Azure OpenAI embeddings: {EMBEDDING_DEPLOYMENT}")

            class AzureEmbedFn(EmbeddingFunction[Documents]):
                def __call__(self, input: Documents) -> Embeddings:
                    response = client.embeddings.create(input=input, model=EMBEDDING_DEPLOYMENT)
                    return [e.embedding for e in response.data]

            return AzureEmbedFn()
    except Exception as e:
        err = str(e)
        if "401" in err or "Unauthorized" in err:
            raise RuntimeError(
                "Azure CLI no autorizado. Ejecuta 'az login'. Auth es AzureCliCredential (misma del inspector)."
            ) from e
        if "404" in err or "DeploymentNotFound" in err:
            print(f"  WARN: Embedding deployment '{EMBEDDING_DEPLOYMENT}' not found on {AZURE_ENDPOINT}")
            print(f"  INFO: Para produccion, crear deployment '{EMBEDDING_DEPLOYMENT}' en este recurso.")
            print(f"  INFO: Usando embeddings locales (Chroma default) como fallback.")
        else:
            print(f"  WARN: Azure embeddings error: {err[:100]}")
            print(f"  INFO: Usando embeddings locales como fallback.")

    # Fallback: Chroma default embedding (local, no Azure needed)
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    print(f"  Using local default embeddings (Chroma built-in).")
    return DefaultEmbeddingFunction()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Force reindex even if collection exists")
    args = parser.parse_args()

    import chromadb

    print(f"KB Dir:    {KB_DIR}")
    print(f"Chroma:    {CHROMA_DIR}")
    print(f"Embedding: {EMBEDDING_DEPLOYMENT}")

    # Find PDFs
    pdfs = list(KB_DIR.glob("*.pdf"))
    if not pdfs:
        print("ERROR: No PDFs found in KB_DIR")
        sys.exit(1)
    print(f"PDFs:      {[p.name for p in pdfs]}")

    # Init Chroma
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Check existing
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing and not args.force:
        col = client.get_collection(COLLECTION_NAME)
        count = col.count()
        if count > 0:
            print(f"Collection '{COLLECTION_NAME}' already has {count} docs. Use --force to reindex.")
            sys.exit(0)

    # Get embedding function
    print("Connecting to Azure OpenAI for embeddings...")
    embed_fn = get_embedding_function()

    # Create/reset collection
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(name=COLLECTION_NAME, embedding_function=embed_fn)

    # Extract and chunk
    all_chunks: list[dict] = []
    for pdf in pdfs:
        print(f"  Extracting: {pdf.name}")
        pages = extract_text_from_pdf(pdf)
        chunks = chunk_pages(pages)
        all_chunks.extend(chunks)
        print(f"    Pages: {len(pages)}, Chunks: {len(chunks)}")

    print(f"Total chunks: {len(all_chunks)}")

    # Add to collection in batches
    BATCH = 50
    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i:i + BATCH]
        ids = [f"chunk_{i + j}" for j in range(len(batch))]
        docs = [c["text"] for c in batch]
        metas = [{"source": c["source"], "page": c["page"], "chunk_start": c["chunk_start"]} for c in batch]
        collection.add(ids=ids, documents=docs, metadatas=metas)
        print(f"  Indexed batch {i // BATCH + 1} ({len(batch)} chunks)")

    print(f"\nDone. Collection '{COLLECTION_NAME}' has {collection.count()} documents.")


if __name__ == "__main__":
    main()
