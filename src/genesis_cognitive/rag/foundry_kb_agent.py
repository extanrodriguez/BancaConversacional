"""Cliente del agente Foundry KB (genesis-kb-agent-poc).

Se usa en path de conocimiento (BUSINESS_KNOWLEDGE / FAQ miss) cuando
GENESIS_FOUNDRY_KB_AGENT=1. No toca saldos ni productos personales.

Mejora: respuestas concisas, grounded en Azure AI Search del agente,
y desambiguación cuando la pregunta KB es ambigua.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any


_FOUNDRY_USER_PREFIX = """Eres el especialista de conocimiento de Banco Santa Cruz (vía Azure AI Search).

Reglas obligatorias:
1) Responde SOLO con información recuperada del índice. No inventes tasas ni requisitos.
2) Sé claro y conciso: 2 a 5 oraciones o viñetas cortas. Sin relleno.
3) Responde en español, tono banca profesional.
4) Certificado de depósito / depósito a plazo = producto de INVERSIÓN/ahorro a plazo.
   NO es una «cuenta» de ahorro/corriente (CA/CC). Tampoco lo confundas con
   «préstamo con garantía de certificados BSC» (eso es un crédito).
5) Si la pregunta es clara (definición, «es una cuenta?», diferencia entre productos),
   responde de frente con evidencia de la KB. Solo pide aclarar si el mensaje es un
   sustantivo ambiguo muy corto (ej. solo «certificado»).
6) No menciones Genesis, RAG, índices ni que eres un agente PoC.
7) Si no hay evidencia en el índice, dilo en una frase y ofrece reformular.
8) NUNCA emitas citas, marcadores ni dumps numéricos: nada de 【n:m†source】,
   [n:m†source], †source, ni tablas/listas tipo | 1 | 2 | 3 |. Solo prosa clara.

"""


def is_foundry_kb_enabled() -> bool:
    return os.getenv("GENESIS_FOUNDRY_KB_AGENT", "").strip().lower() in ("1", "true", "yes", "on")


def foundry_config() -> dict[str, str]:
    return {
        "endpoint": os.getenv(
            "GENESIS_FOUNDRY_PROJECT_ENDPOINT",
            "https://foundry-bsc-genesis-dev.services.ai.azure.com/api/projects/genesis-rag-poc",
        ).rstrip("/"),
        "agent": os.getenv("GENESIS_FOUNDRY_KB_AGENT_NAME", "genesis-kb-agent-poc"),
        "version": os.getenv("GENESIS_FOUNDRY_KB_AGENT_VERSION", "5"),
    }


def _looks_personal_banking(question: str) -> bool:
    """No enviar al agente KB preguntas de portafolio personal."""
    q = (question or "").lower()
    markers = (
        "mi saldo", "mis productos", "mi cuenta", "mi tarjeta", "mi prestamo",
        "mi préstamo", "mi certificado", "mi deposito", "mi depósito",
        "cuanto tengo", "cuánto tengo", "dame mis", "y del ", "transfer",
        "deposito_plazo", "depósito_plazo",
        # Selección corta de producto pendiente (P01: «dame el multicredito»)
        "dame el", "dame la", "la del", "el del",
    )
    return any(m in q for m in markers)


def is_knowledge_ambiguous_question(question: str) -> bool:
    """Preguntas KB que admiten varias lecturas (definición vs proceso vs catálogo)."""
    q = (question or "").strip().lower()
    if not q or _looks_personal_banking(q):
        return False
    # Comparación / definición explícita → no ambigua
    if re.search(
        r"\b(que\s+es|qu[eé]\s+es|definici[oó]n|es\s+una?\s+|son\s+lo\s+mismo|"
        r"diferencia|versus|\bvs\b)\b",
        q,
    ):
        return False
    # Sustantivo solo / muy corto
    if len(q.split()) <= 3 and any(
        s in q
        for s in (
            "certificado",
            "deposito",
            "depósito",
            "dap",
            "cdt",
            "prestamo",
            "préstamo",
            "tarjeta",
            "cuenta corriente",
            "multicredit",
            "multicrédito",
        )
    ):
        return True
    return False


def build_knowledge_ambiguity_clarification(
    question: str,
    display_name: str | None = None,
) -> str | None:
    """Clarificación determinista para ambigüedades KB frecuentes."""
    q = (question or "").lower()
    hello = f"{display_name}, " if display_name else ""
    # Portafolio personal → no bloquear con ambigüedad KB
    if any(
        s in q
        for s in (
            "mis certificado",
            "mi certificado",
            "mi deposito",
            "mi depósito",
            "mis depositos",
            "mis depósitos",
            "mi dap",
            "mis dap",
            "dame mis",
            "mis productos",
            "mi portafolio",
            "que tengo",
            "qué tengo",
            "listame",
            "listar mis",
            "y mi deposito",
            "y mi depósito",
            "y mis certificados",
        )
    ):
        return None
    # Pregunta clara de definición / comparación → responder, no aclarar
    # Ej.: «un depósito a plazo es una cuenta?», «qué es un CD», «diferencia entre…»
    if re.search(
        r"\b("
        r"que\s+es|qu[eé]\s+es|definici[oó]n|significa|"
        r"es\s+una?\s+|son\s+lo\s+mismo|es\s+lo\s+mismo|"
        r"diferencia|versus|\bvs\b|o\s+una\s+cuenta|o\s+un\s+pr[eé]stamo"
        r")\b",
        q,
    ):
        return None
    # Selección de card APK / id de producto → no ambigüedad de glosario
    if (
        "deposito_plazo" in q
        or "depósito_plazo" in q
        or bool(re.search(r"(···|\.{2,}|…|\*{3,}|••••)\s*\d{3,}", q))
        or bool(re.search(r"\bdeposito_plazo[_\s-]?\d{3,}", q))
    ):
        return None
    if any(s in q for s in ("certificado", "deposito a plazo", "depósito a plazo", "dap", "cdt")):
        if "garantia" in q or "garantía" in q or "prestamo" in q or "préstamo" in q:
            return None
        # Solo aclarar si el mensaje es un sustantivo corto sin pregunta definida
        if len(q.split()) <= 4:
            return (
                f"{hello}¿te refieres a la **definición del depósito a plazo / certificado de depósito** "
                f"(producto de inversión) o a un **préstamo con garantía de certificados BSC**?\n\n"
                f"También puedo listar **tus** certificados si lo indicas."
            )
        return None
    if "cuenta corriente" in q or q.strip() in ("cuentas corrientes", "cuenta corrientes"):
        return (
            f"{hello}¿quieres la **definición** de cuenta corriente, el **catálogo** del banco "
            f"o ver **tus** cuentas?"
        )
    if any(s in q for s in ("multicredit", "multicrédito")) and not any(
        s in q
        for s in (
            "condicion", "cargo", "que es", "qué es", "requisito",
            "robo", "roban", "pierdo", "plastico", "plástico",
            "avance", "efectivo", "comision", "comisión", "consumo",
            "cuotas", "diferenc", "disting", "compar", "versus", " vs ",
            "pago", "cancel",
            "dame", "dime", "la del", "el del", "quiero el", "quiero la",
            "seleccion", "selección", "esa tarjeta", "mi tarjeta", "tu tarjeta",
            "adeud", "disponible", "saldo", "limite", "límite", "debo",
        )
    ):
        return (
            f"{hello}¿buscas **qué es** Multicrédito, sus **condiciones/cargos**, "
            f"o info de **tu** tarjeta Multicrédito?"
        )
    return None


def _strip_foundry_citation_noise(text: str) -> str:
    """Quita citas Foundry y dumps `| n |` que a veces contamina output_text."""
    cleaned = text or ""
    # Dumps de índices primero (evitar corchete abierto que trague prosa)
    cleaned = re.sub(
        r"\[\s*\d{1,4}(?:\s*[|/]\s*\d{1,4}){2,}(?:\s*[|/]\s*)?\]?",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?m)^(?:\s*\|\s*\d{1,4}\s*){3,}\|?\s*$", "", cleaned)
    cleaned = re.sub(
        r"(?:\[\s*)?(?:\d{1,4}\s*[|/]\s*){5,}\d{0,4}"
        r"(?:\s*:\s*\d+\s*[†‡+]?\s*source\s*\]?)?"
        r"(?:\s*[】\]])?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"[【\[]\s*\d+\s*:\s*\d+\s*[†‡+]?\s*source\s*[】\]]",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[【\[][^】\]]{0,80}†source[】\]]?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d+\s*:\s*\d+\s*[†‡+]\s*source\s*\]?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?m)^[\s|/0-9]{8,}$", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _compose_user_message(question: str, display_name: str | None) -> str:
    q = (question or "").strip()
    bits = [_FOUNDRY_USER_PREFIX]
    if display_name:
        bits.append(f"Cliente: {display_name}.")
    if is_knowledge_ambiguous_question(q):
        bits.append(
            "La pregunta puede ser ambigua. Si en el índice hay varios sentidos, "
            "prioriza definición de producto (no garantía crediticia) y ofrece aclarar."
        )
    bits.append(f"\nPregunta del cliente:\n{q}")
    return "\n".join(bits)


def ask_foundry_kb_agent(
    question: str,
    *,
    display_name: str | None = None,
    timeout_s: float = 60.0,
    prefer_clarify_ambiguous: bool = True,
    topic: str | None = None,
) -> dict[str, Any]:
    """Invoca genesis-kb-agent-poc vía AIProjectClient / responses API.

    Returns:
      {ok, answer, status, error?}
    """
    if not is_foundry_kb_enabled():
        return {"ok": False, "answer": "", "status": "FOUNDRY_DISABLED", "error": "flag off"}
    if not (question or "").strip():
        return {"ok": False, "answer": "", "status": "FOUNDRY_EMPTY", "error": "empty question"}
    if _looks_personal_banking(question):
        return {
            "ok": False,
            "answer": "",
            "status": "FOUNDRY_SKIP_PERSONAL",
            "error": "personal banking — use snapshot path",
        }

    # Cache hit (solo conocimiento; no personal)
    try:
        from genesis_cognitive.rag.foundry_kb_cache import get_cached

        cached = get_cached(question, topic=topic)
        if cached and cached.get("answer"):
            text = _strip_foundry_citation_noise(str(cached["answer"]))
            if not text or len(text) < 12:
                pass  # cache contaminado: continuar a Foundry
            else:
                if display_name and not text.lower().startswith(display_name.lower()):
                    text = f"{display_name}, {text}"
                return {**cached, "answer": text}
    except Exception:
        pass

    # Clarificación local antes de gastar latencia Foundry (ambiguos cortos)
    if prefer_clarify_ambiguous:
        clarify = build_knowledge_ambiguity_clarification(question, display_name)
        qn = (question or "").strip().lower()
        if clarify and not re.search(
            r"\b(que\s+es|qu[eé]\s+es|definici[oó]n|es\s+una?\s+|diferencia)\b",
            qn,
        ):
            return {
                "ok": True,
                "answer": clarify,
                "status": "FOUNDRY_KB_CLARIFY",
                "agent": foundry_config()["agent"],
                "version": foundry_config()["version"],
            }

    cfg = foundry_config()
    try:
        from azure.identity import DefaultAzureCredential
        from azure.ai.projects import AIProjectClient
    except ImportError as exc:
        return {
            "ok": False,
            "answer": "",
            "status": "FOUNDRY_IMPORT_ERROR",
            "error": f"pip install azure-ai-projects==2.1.0 ({exc})",
        }

    try:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        project_client = AIProjectClient(endpoint=cfg["endpoint"], credential=credential)
        openai_client = project_client.get_openai_client()
        user_content = _compose_user_message(question, display_name)
        response = openai_client.responses.create(
            input=[{"role": "user", "content": user_content}],
            extra_body={
                "agent_reference": {
                    "name": cfg["agent"],
                    "version": str(cfg["version"]),
                    "type": "agent_reference",
                }
            },
            timeout=timeout_s,
        )
        text = (getattr(response, "output_text", None) or "").strip()
        if not text:
            raw = getattr(response, "output", None)
            if raw:
                text = str(raw)[:4000].strip()
        if not text:
            return {"ok": False, "answer": "", "status": "FOUNDRY_EMPTY_RESPONSE", "error": "no output_text"}

        text = _strip_foundry_citation_noise(text)
        if not text or len(text) < 12:
            return {
                "ok": False,
                "answer": "",
                "status": "FOUNDRY_CITATION_NOISE",
                "error": "answer collapsed after citation strip",
            }

        # Post-filtro: si respondió garantía de préstamo a una pregunta de definición DAP
        qn = (question or "").lower()
        low = text.lower()
        if any(s in qn for s in ("certificado", "deposito a plazo", "depósito a plazo", "dap")):
            if "garantía de certificado" in low or "garantia de certificado" in low or "préstamo personal mediante" in low:
                if "inversión" not in low and "inversion" not in low and "depósito a plazo" not in low:
                    clarify = build_knowledge_ambiguity_clarification(question, display_name)
                    if clarify:
                        return {
                            "ok": True,
                            "answer": clarify,
                            "status": "FOUNDRY_KB_CLARIFY",
                            "agent": cfg["agent"],
                            "version": cfg["version"],
                        }

        if display_name and not text.lower().startswith(display_name.lower()):
            text = f"{display_name}, {text}"
        result = {
            "ok": True,
            "answer": text,
            "status": "FOUNDRY_KB_ANSWERED",
            "agent": cfg["agent"],
            "version": cfg["version"],
        }
        try:
            from genesis_cognitive.rag.foundry_kb_cache import put_cached as _put

            # Guardar sin saludo personalizado para reutilizar entre clientes
            to_store = dict(result)
            raw_ans = text
            if display_name and raw_ans.lower().startswith(display_name.lower()):
                raw_ans = raw_ans[len(display_name):].lstrip(" ,:")
                to_store["answer"] = raw_ans
            _put(question, to_store, topic=topic)
        except Exception:
            pass
        return result
    except Exception as exc:
        print(f"[FOUNDRY_KB] error: {exc}", file=sys.stderr)
        return {
            "ok": False,
            "answer": "",
            "status": "FOUNDRY_ERROR",
            "error": str(exc)[:300],
        }
