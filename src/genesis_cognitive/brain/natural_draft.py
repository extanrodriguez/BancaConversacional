"""Redacción natural Azure SOBRE hechos ya resueltos (no inventa números)."""

from __future__ import annotations

import os
import re
from typing import Any


_SYSTEM = """Eres el redactor de Banca Conversacional de Banco Santa Cruz.
Recibirás HECHOS ya verificados y la pregunta del cliente.
Reescribe en español natural, claro y profesional (tú).

REGLAS DURAS:
1) No agregues montos, fechas, tasas ni productos que no estén en HECHOS.
2) No inventes cuotas, ni digas que un dato existe si HECHOS dice que no está disponible.
3) Puedes suavizar el tono y ordenar la información.
4) Mantén máscaras/últimos dígitos tal cual.
5) 1 a 4 oraciones o viñetas cortas. Sin mencionar Azure, RAG ni sistemas internos.
6) Si HECHOS ya está bien, puedes devolverlo casi igual.
"""


def is_azure_draft_enabled() -> bool:
    # Por defecto ON si el brain está ON; se puede apagar con GENESIS_AZURE_DRAFT=0
    explicit = os.getenv("GENESIS_AZURE_DRAFT", "").strip().lower()
    if explicit in ("0", "false", "no", "off"):
        return False
    if explicit in ("1", "true", "yes", "on"):
        return True
    return os.getenv("GENESIS_AZURE_BRAIN", "").strip().lower() in ("1", "true", "yes", "on")


def _extract_anchors(text: str) -> set[str]:
    """Números/fechas/máscaras que deben sobrevivir o no inventarse de más."""
    t = text or ""
    anchors = set(re.findall(r"\d{4}-\d{2}-\d{2}", t))
    anchors |= set(re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", t))
    anchors |= set(re.findall(r"\d+\.\d{2}", t))
    anchors |= set(re.findall(r"\*{2,}\d{3,4}|\d{4}", t))
    return {a for a in anchors if a}


async def draft_natural_async(
    question: str,
    facts_text: str,
    *,
    display_name: str | None = None,
) -> str:
    """Redacta facts_text. Si falla validación/API → devuelve facts_text."""
    base = (facts_text or "").strip()
    if not base or not is_azure_draft_enabled():
        return base

    # No reescribir clarificaciones cortas de selección ni chitchat ya natural
    low = base.lower()
    if ("¿quieres consultar" in low or "deseas consultar" in low) and " o " in low:
        return base
    if any(
        s in low
        for s in (
            "aquí estoy",
            "me desvié del tema",
            "con gusto",
            "cuando quieras, dime",
        )
    ):
        return base
    # Procesos regulatorios largos se estructuran después en rich_content;
    # no resumir ni alterar pasos/documentos con el redactor generativo.
    if (
        ("cliente fallecido" in low or "de cujus" in low)
        and "etapas del proceso" in low
    ):
        return base

    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    if not api_key or not endpoint:
        return base

    user = (
        f"Cliente: {display_name or 'Cliente'}\n"
        f"Pregunta: {question}\n\n"
        f"HECHOS:\n{base}\n\n"
        "Respuesta natural:"
    )
    try:
        from openai import AsyncAzureOpenAI

        client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )
        resp = await client.chat.completions.create(
            model=deployment,
            temperature=0.3,
            max_tokens=450,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
        )
        drafted = (resp.choices[0].message.content or "").strip()
        if not drafted:
            return base
        # Validación anti-alucinación: no introducir anclas nuevas significativas
        base_anchors = _extract_anchors(base)
        draft_anchors = _extract_anchors(drafted)
        # Permitir subset; bloquear si aparecen montos/fechas nuevas
        extra = draft_anchors - base_anchors
        # Filtrar anclas triviales de 1-2 dígitos (días de corte pueden repetirse)
        suspicious = {e for e in extra if re.search(r"\d{3,}", e) or re.search(r"\d{4}-\d{2}-\d{2}", e)}
        if suspicious:
            return base
        # No debe inventar cuota si facts dicen no disponible
        if "no tengo el monto de la cuota" in base.lower() and re.search(
            r"cuota.{0,40}\d{3,}", drafted.lower()
        ):
            return base
        return drafted
    except Exception:
        return base


def draft_natural(
    question: str,
    facts_text: str,
    *,
    display_name: str | None = None,
) -> str:
    """Sync no-op wrapper (tests); use draft_natural_async en runtime."""
    return (facts_text or "").strip()
