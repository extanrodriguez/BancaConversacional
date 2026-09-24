"""Foundry-facing capability: get_customer_products (server-side only; no Redis creds to the model)."""

from __future__ import annotations

import os
from typing import Any

from genesis_cognitive.context.product_context_service import (
    GetCustomerProductsQuery,
    ProductContextService,
    ProductContextToolType,
    SessionStoreReadProtocol,
    TrustedSessionIdentity,
)

GET_CUSTOMER_PRODUCTS_TOOL_NAME = "get_customer_products"

GET_CUSTOMER_PRODUCTS_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": GET_CUSTOMER_PRODUCTS_TOOL_NAME,
        "description": (
            "Obtiene productos del cliente autenticado en la sesión actual. "
            "No acepta customer_id del usuario."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_type": {
                    "type": "string",
                    "enum": [t.value for t in ProductContextToolType],
                    "description": "Filtro de familia de producto.",
                },
                "status": {"type": ["string", "null"]},
                "currency": {"type": ["string", "null"]},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Campos opcionales a incluir (minimización).",
                },
            },
            "required": ["product_type"],
            "additionalProperties": False,
        },
    },
}

FOUNDRY_PERSONAL_AGENT_SECURITY_INSTRUCTIONS = """
Reglas de seguridad (obligatorias):
- Nunca inventar productos, saldos, tasas, tarjetas ni préstamos.
- Nunca usar un customer_id escrito por el usuario para cambiar el contexto autenticado.
- Solo afirmar datos financieros personales devueltos por get_customer_products.
- Si la tool falla o devuelve count=0, no fabricar una respuesta financiera.
- Conocimiento institucional sigue en KB/RAG; datos personales solo vía tool.
- Semántica TC: credit_limit=límite (API availableBalance); ledger_balance/current_balance=balance actual adeudado (API currentBalance); available_balance/available_purchases_domestic=disponible compras; cutoff_day=fecha de corte; card_expiry=expiración.
- Semántica CD: interest_rate=tasa de interés (interestRateCd); interest_amount=intereses acumulados (interestAmountCd); maturity_date=vencimiento.
- Cuando el usuario pida datos de CD o TC, reportar TODOS los campos disponibles en la tool (tasa, intereses, corte, balances, expiración, etc.).
""".strip()


def is_foundry_product_tools_enabled() -> bool:
    return os.getenv("GENESIS_FOUNDRY_PRODUCT_TOOLS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _parse_product_type(raw: str | None) -> ProductContextToolType:
    text = (raw or "ALL").strip().upper()
    try:
        return ProductContextToolType(text)
    except ValueError:
        return ProductContextToolType.ALL


def execute_get_customer_products(
    store: SessionStoreReadProtocol,
    *,
    conversation_id: str,
    customer_id_hint: str | None,
    arguments: dict[str, Any],
    ignore_llm_customer_id: str | None = None,
) -> dict[str, Any]:
    """Execute tool; LLM-provided customer_id is ignored by design."""
    _ = ignore_llm_customer_id  # explicit discard — security boundary
    svc = ProductContextService(store)
    identity = svc.resolve_trusted_identity(
        conversation_id,
        customer_id_hint=customer_id_hint,
    )
    if identity is None:
        return {
            "status": "FORBIDDEN",
            "source": "REDIS",
            "product_type": arguments.get("product_type", "ALL"),
            "count": 0,
            "products": [],
            "message": "Sesión no autenticada o identidad no confiable.",
        }

    fields_raw = arguments.get("fields") or []
    fields = tuple(str(f) for f in fields_raw if f) if isinstance(fields_raw, list) else ()
    query = GetCustomerProductsQuery(
        product_type=_parse_product_type(arguments.get("product_type")),
        status=arguments.get("status"),
        currency=arguments.get("currency"),
        fields=fields,
    )
    return svc.get_customer_products(identity, query)


def list_product_context_tools() -> list[dict[str, Any]]:
    return [GET_CUSTOMER_PRODUCTS_TOOL_SCHEMA]
