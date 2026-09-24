"""Azure RAG retrieval — AI Search vector store + Azure OpenAI generation.

Auth: API keys from environment variables; no interactive Azure CLI dependency.
Retrieves context from indexed KB and generates grounded answers.
Does NOT access customer balances/loans. Only bank general knowledge.
"""

from __future__ import annotations

import os
from typing import Any

AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://aoai-genesis-871a5b-7e0e0.openai.azure.com/")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "https://genesis-search-lab.search.windows.net")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "genesis-kb")


def _get_search_key() -> str:
    """Return the AI Search key from the protected runtime environment."""
    return os.getenv("AZURE_SEARCH_API_KEY", "").strip()


class LocalRagStore:
    """Azure AI Search-based RAG store."""

    def __init__(self) -> None:
        self._search_key = ""
        self._status = "not_indexed"
        self._init()

    def _init(self) -> None:
        try:
            self._search_key = _get_search_key()
            if not self._search_key:
                self._status = "error: no search key"
                return
            # Check document count
            import httpx
            r = httpx.get(
                f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/$count?api-version=2024-07-01",
                headers={"api-key": self._search_key},
                timeout=10.0,
            )
            if r.status_code == 200:
                count = int(r.text.strip())
                self._status = "ready" if count > 0 else "not_indexed"
            else:
                self._status = f"error: search {r.status_code}"
        except Exception as e:
            self._status = f"error: {str(e)[:60]}"

    @property
    def status(self) -> str:
        return self._status

    def query(self, question: str, top_k: int = 4) -> dict[str, Any]:
        """Vector search in Azure AI Search. Returns chunks + rag_status.

        Uses sync httpx (called from async context via run_in_executor if needed,
        but httpx sync works fine in uvicorn threads).
        """
        if self._status != "ready":
            return {"chunks": [], "rag_status": "NO_HITS"}

        try:
            # Get embedding for the question
            embedding = self._embed_query(question)
            if not embedding:
                import sys
                print("[RAG] query: embedding returned None", file=sys.stderr)
                return {"chunks": [], "rag_status": "NO_HITS"}

            # Vector search (sync httpx — safe in uvicorn thread pool)
            import httpx
            url = f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}/docs/search?api-version=2024-07-01"
            body = {
                "count": True,
                "top": top_k,
                "vectorQueries": [{
                    "kind": "vector",
                    "vector": embedding,
                    "fields": "content_vector",
                    "k": top_k,
                }],
                "select": "content,source,document_name",
            }
            with httpx.Client(timeout=15.0) as client:
                r = client.post(url, headers={"api-key": self._search_key, "Content-Type": "application/json"}, json=body)

            if r.status_code != 200:
                import sys
                print(f"[RAG] search returned {r.status_code}: {r.text[:200]}", file=sys.stderr)
                return {"chunks": [], "rag_status": "NO_HITS"}

            data = r.json()
            results = data.get("value", [])
            if not results:
                return {"chunks": [], "rag_status": "NO_HITS"}

            chunks = []
            for doc in results:
                chunks.append({
                    "text": (doc.get("content") or "")[:500],
                    "source": doc.get("source") or doc.get("document_name") or "?",
                    "page": 0,
                    "score": doc.get("@search.score", 0),
                })

            return {"chunks": chunks, "rag_status": "HITS"}
        except Exception as e:
            import sys
            print(f"[RAG] query exception: {e}", file=sys.stderr)
            return {"chunks": [], "rag_status": "NO_HITS"}

    def _embed_query(self, text: str) -> list[float] | None:
        """Embed a single query using Azure OpenAI (same auth as inspector)."""
        try:
            from openai import AzureOpenAI

            api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("AZURE_OPENAI_API_KEY missing for RAG embeddings")
            client = AzureOpenAI(
                azure_endpoint=AZURE_ENDPOINT,
                api_version=AZURE_API_VERSION,
                api_key=api_key,
            )
            resp = client.embeddings.create(input=[text], model=EMBEDDING_DEPLOYMENT)
            return resp.data[0].embedding
        except Exception as e:
            import sys
            print(f"[RAG] _embed_query ERROR: {e}", file=sys.stderr)
            return None


async def generate_rag_answer(
    question: str,
    chunks: list[dict[str, Any]],
    display_name: str | None = None,
    conversation_id: str | None = None,
) -> str:
    """Generate a professional banking answer grounded in retrieved KB fragments.

    Rules:
    - Professional banking advisor tone, 2-5 sentences.
    - NEVER mention: Genesis, base de conocimiento, RAG, Knowledge_Base, PDF names,
      "no cuento con el detalle", "acudir a un asesor o canal oficial".
    - Use ONLY info from chunks; do NOT invent rates or requirements.
    - If fragments insufficient: generate human-case fallback with case number.
    """
    if not chunks:
        return _human_case_fallback(question, conversation_id, display_name)

    # Build context (aggressively clean project headers from chunks before LLM sees them)
    _SKIP_PHRASES = (
        "Proyecto Genesis", "Base de Conocimiento RAG", "Documento de trabajo",
        "validacion institucional", "Uso interno", "No contiene datos reales",
        "source_type", "document_name", "chunk_id", "KB_GENESIS",
        "sensitivity_level", "controlled_operation", "execution_allowed",
        "requires_authentication", "requires_confirmation", "environment",
        "domain_category", "product_type\":", "intent\":", "transactional",
        "**Producto:**", "**Intencion:**", "**Intención:**", "**Funcionalidad:**",
        "**Expresiones del cliente:**", "Respuesta / contexto aprobado",
        "- Producto:", "- Intencion:", "- Intención:", "- Funcionalidad:",
        "- Expresiones del cliente:",
    )
    context_parts = []
    for i, c in enumerate(chunks[:4], 1):
        lines = c["text"][:500].split("\n")
        clean_lines = [l.strip() for l in lines
                       if l.strip() and not any(sk in l for sk in _SKIP_PHRASES)]
        clean_text = " ".join(clean_lines)
        if len(clean_text) > 20:
            context_parts.append(f"[{i}] {clean_text}")
    context = "\n\n".join(context_parts) if context_parts else ""

    if not context:
        return _human_case_fallback(question, conversation_id, display_name)

    # LLM generation
    try:
        from agent_framework import Agent, ChatOptions, Message
        from agent_framework.openai import OpenAIChatCompletionClient

        api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY missing for RAG generation")
        deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini")
        client = OpenAIChatCompletionClient(
            model=deployment,
            azure_endpoint=AZURE_ENDPOINT,
            api_version=AZURE_API_VERSION,
            api_key=api_key,
        )

        system_prompt = (
            "Eres un asesor bancario profesional que responde consultas de productos y politicas generales del banco. "
            "Reglas:\n"
            "- Responde en espanol claro, cordial, entre 2 y 5 frases.\n"
            "- Extrae la informacion util de los datos proporcionados, aunque esten en formato tecnico o parcial.\n"
            "- No inventes tasas, requisitos ni cifras que no aparezcan en los datos.\n"
            "- Si hay informacion relevante aunque parcial, compartela de forma clara al cliente.\n"
            "- Solo si los datos NO contienen absolutamente nada relacionado con la pregunta, "
            "responde: 'INSUFFICIENT_DATA'\n"
            "- NUNCA menciones: 'Genesis', 'base de conocimiento', 'RAG', 'Knowledge_Base', 'PDF', 'documento de trabajo', "
            "'fragmentos', 'contexto', 'json', 'metadatos', ni nombres de archivos.\n"
            "- Habla como si fueras el banco directamente, con tono profesional.\n"
            "- Puedes saludar brevemente por nombre si se proporciona."
        )
        greeting_ctx = f"Cliente: {display_name}. " if display_name else ""
        user_content = f"{greeting_ctx}Pregunta del cliente: {question}\n\nInformacion disponible:\n{context}"

        agent: Agent[Any] = Agent(client, instructions=system_prompt, name="RagBankAdvisor")
        messages = [Message(role="user", contents=[user_content])]
        response = await agent.run(messages, options=ChatOptions(temperature=0.3))

        # Extract answer — use response.text (not .value which is for structured output)
        import sys as _sys
        answer = response.text or ""
        print(f"[RAG-LLM] response.text={repr(answer[:80]) if answer else 'EMPTY'}", file=_sys.stderr)
        if not answer or answer == "None":
            answer = _build_fallback_answer(chunks, display_name, question, conversation_id)

        # If LLM explicitly said insufficient
        if "INSUFFICIENT_DATA" in answer:
            return _human_case_fallback(question, conversation_id, display_name)

        # Post-filter
        answer = _sanitize_answer(answer, question, conversation_id, display_name)
        return answer.strip()
    except Exception:
        answer = _build_fallback_answer(chunks, display_name, question, conversation_id)
        return _sanitize_answer(answer, question, conversation_id, display_name)


def _generate_case_number(question: str, conversation_id: str | None) -> str:
    """Generate a stable 7-digit case number from question + conversation_id."""
    import hashlib
    seed = f"{conversation_id or 'default'}:{question}"
    h = hashlib.sha256(seed.encode()).hexdigest()
    # Take first 7 digits from hex converted to int
    num = int(h[:8], 16) % 9_000_000 + 1_000_000  # 7 digits: 1000000-9999999
    return str(num)


def _is_institutional_question(question: str) -> bool:
    """Preguntas institucionales básicas: no escalar a humano si RAG falla."""
    q = (question or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        q = q.replace(a, b)
    # No tratar como institucional consultas de productos/procesos
    product_or_process = (
        "producto", "productos", "prestamo", "prestamos", "cuenta", "cuentas",
        "tarjeta", "tarjetas", "reclam", "reclamo", "proceso", "requisito",
        "cancelacion", "garantia", "solicitar", "contratar", "sacar", "catalogo",
    )
    if any(k in q for k in product_or_process):
        return False
    keys = (
        "mision", "vision", "banco santa cruz", "que es bsc", "hablame del banco",
        "cuentame del banco", "sobre el banco", "que es el banco", "quienes son",
        "informacion del banco", "valores del banco",
    )
    return any(k in q for k in keys)


def _institutional_fallback(display_name: str | None) -> str:
    greeting = f"{display_name}, " if display_name else ""
    return (
        f"{greeting}Banco Santa Cruz es una institución financiera orientada a empresas e "
        "individuos emprendedores. Acompañamos a nuestros clientes con productos y servicios "
        "a su medida, con un estilo de servicio oportuno y excepcional.\n\n"
        "Nuestra visión es ser el Banco preferido de nuestros clientes, ofreciendo un servicio "
        "conveniente, transparente y simple.\n\n"
        "¿Te gustaría conocer nuestra misión, visión o algún producto?"
    )


def _knowledge_intent_fallback(question: str, display_name: str | None) -> str | None:
    """Si FAQ/Azure no alcanzan: interpretar intención contra KB local y responder grounded."""
    try:
        from genesis_cognitive.rag.kb_intent_resolver import (
            is_business_knowledge_question,
            resolve_knowledge_intent,
        )
    except Exception:
        return None
    if not is_business_knowledge_question(question):
        return None
    hit = resolve_knowledge_intent(question)
    if not hit or not hit.get("answer"):
        return None
    answer = str(hit["answer"]).strip()
    if len(answer) < 40:
        return None
    greeting = f"{display_name}, " if display_name else ""
    if greeting and answer.lower().startswith((display_name or "").lower()):
        return answer
    return f"{greeting}{answer}".strip()


def _human_case_fallback(question: str, conversation_id: str | None, display_name: str | None) -> str:
    """Generate fallback. Institucional / intención KB → respuesta; último recurso → humano."""
    if os.getenv("GENESIS_RAG_NO_HUMAN_ESCALATION_INSTITUTIONAL", "1").strip() not in ("0", "false", "False"):
        if _is_institutional_question(question):
            return _institutional_fallback(display_name)
    # Interpretar intención sobre corpus FAQ+MD antes de escalar a asesor
    kb_ans = _knowledge_intent_fallback(question, display_name)
    if kb_ans:
        return kb_ans
    case_id = _generate_case_number(question, conversation_id)
    greeting = f"{display_name}, un" if display_name else "Un"
    return f"{greeting} asesor se pondra en contacto contigo para resolver tu inquietud. Numero de caso #{case_id}."


def _build_fallback_answer(chunks: list[dict[str, Any]], display_name: str | None,
                           question: str, conversation_id: str | None) -> str:
    """Build a professional fallback from chunk content (no LLM)."""
    # Combine all chunk texts and extract useful sentences
    combined = " ".join(c["text"][:300] for c in chunks[:3])

    # Aggressively remove document metadata noise
    import re
    noise_patterns = [
        r"Proyecto Genesis[^.]*\.",
        r"Base de Conocimiento[^.]*\.",
        r"Documento de trabajo[^.]*\.",
        r"Knowledge_Base[^.]*\.",
        r"Asistente Bancario[^.]*\.",
        r"para validaci[oó]n institucional[^.]*\.",
        r"Uso interno[^.]*\.",
        r"No contiene datos reales[^.]*\.",
        r"Pregunta t[ií]pica:[^?]*\?",
        r"Respuesta\s*:",
    ]
    for p in noise_patterns:
        combined = re.sub(p, "", combined, flags=re.IGNORECASE)

    # Extract sentences that look like actual banking content
    sentences = [s.strip() for s in re.split(r"[.!?]+", combined) if len(s.strip()) > 20]
    # Filter out sentences with forbidden words
    forbidden_words = {"genesis", "knowledge", "documento", "validacion", "institucional", "uso interno"}
    useful = [s for s in sentences if not any(fw in s.lower() for fw in forbidden_words)]

    if useful:
        content = ". ".join(useful[:3]) + "."
        greeting = f"{display_name}, " if display_name else ""
        return f"{greeting}{content}"

    return _human_case_fallback(question, conversation_id, display_name)


def _sanitize_answer(answer: str, question: str, conversation_id: str | None,
                     display_name: str | None) -> str:
    """Remove leaked internal references. If answer collapses, use human-case fallback."""
    import re
    from genesis_cognitive.context.response_formatting import sanitize_client_facing_text

    answer = sanitize_client_facing_text(answer)
    forbidden = [
        r"[Pp]royecto\s+[Gg]enesis",
        r"[Bb]ase\s+de\s+[Cc]onocimiento",
        r"\bRAG\b",
        r"Knowledge[_\s]Base",
        r"[Dd]ocumento\s+de\s+trabajo",
        r"KB_GENESIS\S*",
        r"fragmentos?\s+recuperados?",
        r"contexto\s+recuperado",
        r"segun\s+(nuestra|la)\s+base",
        r"no\s+cuento\s+con\s+el\s+detalle",
        r"acudir\s+a\s+un\s+asesor\s+o\s+al\s+canal\s+oficial",
        r"canal\s+oficial\s+del\s+banco",
    ]
    for pattern in forbidden:
        answer = re.sub(pattern, "", answer, flags=re.IGNORECASE)
    answer = re.sub(r"\s{2,}", " ", answer).strip()
    # Remove trailing/leading punctuation artifacts
    answer = answer.strip(" .;,")

    if len(answer) < 15:
        return _human_case_fallback(question, conversation_id, display_name)
    return answer

