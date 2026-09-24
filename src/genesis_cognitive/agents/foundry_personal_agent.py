"""Foundry/Azure personal agent — tool calling sobre ProductContextService.

READ PATH (flag GENESIS_FOUNDRY_PRODUCT_TOOLS=1):
  pregunta → LLM elige get_customer_products → ProductContextService → Redis → respuesta

No expone Redis al modelo. customer_id solo desde sesión confiable.
Si el flag está off o falla, el caller debe continuar el pipeline existente.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from genesis_cognitive.agents.product_context_tools import (
    FOUNDRY_PERSONAL_AGENT_SECURITY_INSTRUCTIONS,
    GET_CUSTOMER_PRODUCTS_TOOL_NAME,
    GET_CUSTOMER_PRODUCTS_TOOL_SCHEMA,
    execute_get_customer_products,
    is_foundry_product_tools_enabled,
)
from genesis_cognitive.context.product_context_service import SessionStoreReadProtocol

_log = logging.getLogger("genesis.foundry.personal")

_PERSONAL_MARKERS = (
    "mis productos",
    "lista mis",
    "listame mis",
    "listar mis",
    "cuáles son mis",
    "cuales son mis",
    "muéstrame mis",
    "muestrame mis",
    "dame mis",
    "ver mis",
    "mi saldo",
    "mis cuentas",
    "mis prestamos",
    "mis préstamos",
    "mis tarjetas",
    "mis depositos",
    "mis depósitos",
    "mis certificados",
    "mi portafolio",
    "que productos tengo",
    "qué productos tengo",
    "cuanto tengo",
    "cuánto tengo",
)

_OPENAI_TOOL = {
    "type": "function",
    "function": GET_CUSTOMER_PRODUCTS_TOOL_SCHEMA["function"],
}


def looks_like_personal_portfolio_query(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    return any(m in q for m in _PERSONAL_MARKERS)


def _system_prompt(display_name: str | None) -> str:
    name = display_name or "Cliente"
    return (
        f"Eres el asistente de banca conversacional de Banco Santa Cruz para {name}.\n"
        f"{FOUNDRY_PERSONAL_AGENT_SECURITY_INSTRUCTIONS}\n"
        "Usa la tool get_customer_products cuando necesites datos del portafolio.\n"
        "Responde en español, tono profesional, conciso (2-6 oraciones o viñetas).\n"
        "No menciones Redis, tools, Foundry ni IDs internos.\n"
    )


async def run_foundry_personal_turn(
    *,
    question: str,
    store: SessionStoreReadProtocol,
    conversation_id: str,
    customer_id: str,
    display_name: str | None = None,
    max_tool_rounds: int = 3,
) -> dict[str, Any] | None:
    """Ejecuta turno personal con tool calling. None = skip / fallthrough."""
    if not is_foundry_product_tools_enabled():
        return None
    if not looks_like_personal_portfolio_query(question):
        return None

    api_key = (os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    if not api_key or not endpoint:
        _log.warning("foundry_personal_skip: missing azure openai config")
        return None

    try:
        from openai import AsyncAzureOpenAI
    except ImportError:
        return None

    client = AsyncAzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(display_name)},
        {"role": "user", "content": (question or "").strip()},
    ]
    tool_trace: list[dict[str, Any]] = []

    try:
        for _round in range(max_tool_rounds):
            resp = await client.chat.completions.create(
                model=deployment,
                temperature=0,
                max_tokens=700,
                tools=[_OPENAI_TOOL],
                tool_choice="auto",
                messages=messages,
            )
            choice = resp.choices[0] if resp.choices else None
            if choice is None:
                return None
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                text = (msg.content or "").strip()
                if not text:
                    return None
                # Anti-alucinación mínima: si no hubo tool y habla de montos, forzar tool
                if re.search(r"\d{3,}", text) and not tool_trace:
                    forced = execute_get_customer_products(
                        store,
                        conversation_id=conversation_id,
                        customer_id_hint=customer_id,
                        arguments={"product_type": "ALL"},
                        ignore_llm_customer_id=None,
                    )
                    tool_trace.append({"name": GET_CUSTOMER_PRODUCTS_TOOL_NAME, "result_status": forced.get("status")})
                    text = _format_fallback_from_tool(forced, display_name)
                return {
                    "ok": True,
                    "text": text,
                    "status": "VALID_CONTRACT",
                    "intent_id": "FOUNDRY_PERSONAL_PRODUCTS",
                    "tool_trace": tool_trace,
                    "provider": "AZURE_OPENAI",
                    "path": "foundry_personal_tools",
                    "model": deployment,
                }

            # Append assistant message with tool_calls
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or "{}",
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}

                # Security: strip any customer_id the model invented
                llm_cid = args.pop("customer_id", None)

                if name != GET_CUSTOMER_PRODUCTS_TOOL_NAME:
                    result = {
                        "status": "UNSUPPORTED_TOOL",
                        "message": f"Tool no permitida: {name}",
                        "products": [],
                        "count": 0,
                    }
                else:
                    result = execute_get_customer_products(
                        store,
                        conversation_id=conversation_id,
                        customer_id_hint=customer_id,
                        arguments=args,
                        ignore_llm_customer_id=str(llm_cid) if llm_cid else None,
                    )

                tool_trace.append(
                    {
                        "name": name,
                        "args": {k: v for k, v in args.items() if k != "customer_id"},
                        "result_status": result.get("status"),
                        "count": result.get("count"),
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

                if result.get("status") in ("FORBIDDEN", "NO_CONTEXT"):
                    # No fabricar: respuesta honesta sin segundo round inventado
                    return {
                        "ok": True,
                        "text": _safe_failure_message(result, display_name),
                        "status": "VALID_CONTRACT"
                        if result.get("status") == "NO_CONTEXT"
                        else "NON_OPERATIONAL",
                        "intent_id": "FOUNDRY_PERSONAL_PRODUCTS",
                        "tool_trace": tool_trace,
                        "provider": "AZURE_OPENAI",
                        "path": "foundry_personal_tools",
                        "model": deployment,
                    }

        # Max rounds exceeded — last tool result as fallback
        last_ok = next(
            (t for t in reversed(tool_trace) if t.get("result_status") == "OK"),
            None,
        )
        if last_ok:
            # Re-fetch ALL for deterministic summary
            forced = execute_get_customer_products(
                store,
                conversation_id=conversation_id,
                customer_id_hint=customer_id,
                arguments={"product_type": "ALL"},
            )
            return {
                "ok": True,
                "text": _format_fallback_from_tool(forced, display_name),
                "status": "VALID_CONTRACT",
                "intent_id": "FOUNDRY_PERSONAL_PRODUCTS",
                "tool_trace": tool_trace,
                "provider": "AZURE_OPENAI",
                "path": "foundry_personal_tools_fallback",
                "model": deployment,
            }
        return None
    except Exception as exc:  # noqa: BLE001
        _log.warning("foundry_personal_failed: %s", type(exc).__name__)
        return None


def _safe_failure_message(result: dict[str, Any], display_name: str | None) -> str:
    hello = f"{display_name}, " if display_name else ""
    status = result.get("status")
    if status == "NO_CONTEXT":
        return (
            f"{hello}aún no tengo cargado tu portafolio en esta sesión. "
            "Vuelve a iniciar sesión o espera a que se sincronice el contexto."
        )
    if status == "FORBIDDEN":
        return (
            f"{hello}no puedo consultar productos de otro cliente. "
            "Solo puedo ayudarte con tu sesión autenticada."
        )
    return f"{hello}no pude consultar tus productos en este momento. Intenta de nuevo."


def _format_fallback_from_tool(result: dict[str, Any], display_name: str | None) -> str:
    hello = f"{display_name}, " if display_name else ""
    if result.get("status") != "OK" or not result.get("products"):
        return _safe_failure_message(result, display_name)
    lines: list[str] = [f"{hello}estos son tus productos:"]
    for p in result["products"][:12]:
        ptype = p.get("product_type", "PRODUCTO")
        ref = p.get("product_ref", "")
        cur = p.get("currency", "")
        bits = [f"- {ptype} `{ref}`"]
        if cur:
            bits.append(f"({cur})")
        bal = p.get("available_balance")
        if bal is None:
            bal = p.get("ledger_balance")
        if bal is None:
            bal = p.get("outstanding_balance")
        if bal is not None:
            bits.append(f"— {bal}")
        lines.append(" ".join(bits))
    return "\n".join(lines)
