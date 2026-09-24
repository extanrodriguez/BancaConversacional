"""Bootstrap de portafolio vía Presentation Product (mismo origen que el orch .NET).

Replica el GET de BankingApiClient.GetPresentationProductAsync +
ChatWebSocketHandler.BuildInitialContextData, sin tocar el backend .NET.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_PRESENTATION_PRODUCT_URL_TEMPLATE = (
    "https://apigateway-gen.qa.bsc.com.do/api/presentation/product/{customerId}"
)
DEFAULT_FIRST_NAME = "Cliente"


def presentation_product_url(customer_id: str, template: str | None = None) -> str:
    tpl = (
        (template or "").strip()
        or os.getenv("GENESIS_PRESENTATION_PRODUCT_URL_TEMPLATE", "").strip()
        or DEFAULT_PRESENTATION_PRODUCT_URL_TEMPLATE
    )
    cid = urllib.parse.quote(str(customer_id).strip(), safe="")
    return (
        tpl.replace("{customerId}", cid)
        .replace("{clientId}", cid)
        .replace("{clientIdentifier}", cid)
    )


def _allow_insecure_tls() -> bool:
    raw = (os.getenv("GENESIS_PRESENTATION_ALLOW_INSECURE_TLS") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _timeout_s() -> float:
    try:
        return float(os.getenv("GENESIS_PRESENTATION_TIMEOUT_S", "25"))
    except ValueError:
        return 25.0


def normalize_presentation_payload(payload: Any) -> dict[str, Any]:
    """Normaliza la respuesta del API gateway al envelope Core que consume /turn.

    Equivalente a BuildInitialContextData del orquestador .NET:
    { primerNombre, resultCode, resultMessage, products: [...] }
    """
    if not isinstance(payload, dict):
        raise ValueError("presentation_payload_not_object")

    # Transport wrapper: { isSucceded, code, message, data: {...} }
    has_wrapper = any(k in payload for k in ("isSucceded", "isSucceeded", "code", "message"))
    inner = payload.get("data")
    if has_wrapper and isinstance(inner, dict):
        data: dict[str, Any] = dict(inner)
    elif has_wrapper and isinstance(inner, list):
        data = {"products": list(inner)}
    else:
        data = dict(payload)

    for key in ("isSucceded", "isSucceeded", "code", "message"):
        data.pop(key, None)

    # Algunos payloads traen products en data[] anidado
    nested = data.get("data")
    if isinstance(nested, list) and not (
        isinstance(data.get("products"), list) and data["products"]
    ):
        data["products"] = list(nested)
        data.pop("data", None)

    if not isinstance(data.get("products"), list):
        # Normalizado del orch: products en raíz del wrapper
        if isinstance(payload.get("products"), list):
            data["products"] = list(payload["products"])
        else:
            data["products"] = []

    primer = data.get("primerNombre")
    if not isinstance(primer, str) or not primer.strip():
        data["primerNombre"] = DEFAULT_FIRST_NAME

    if "resultCode" not in data:
        data["resultCode"] = 0
    if not data.get("resultMessage"):
        data["resultMessage"] = "Consulta realizada exitosamente."

    return data


def fetch_presentation_product(customer_id: str) -> dict[str, Any]:
    """GET Presentation Product y devuelve envelope normalizado (listo para /turn)."""
    url = presentation_product_url(customer_id)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "genesis-cognitive-pruebas/1.0",
        },
        method="GET",
    )
    ctx = None
    if url.lower().startswith("https://") and _allow_insecure_tls():
        ctx = ssl._create_unverified_context()  # noqa: S323 — paridad AllowInsecureBankingTls del orch

    try:
        with urllib.request.urlopen(req, timeout=_timeout_s(), context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            json.dumps(
                {
                    "error": "presentation_product_http_error",
                    "status": exc.code,
                    "url": url,
                    "body": body[:800],
                },
                ensure_ascii=False,
            )
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            json.dumps(
                {
                    "error": "presentation_product_unreachable",
                    "url": url,
                    "message": str(exc),
                },
                ensure_ascii=False,
            )
        ) from exc

    if not raw.strip():
        raise RuntimeError(
            json.dumps({"error": "presentation_product_empty", "url": url}, ensure_ascii=False)
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            json.dumps(
                {
                    "error": "presentation_product_not_json",
                    "url": url,
                    "status": status,
                    "body": raw[:400],
                },
                ensure_ascii=False,
            )
        ) from exc

    data = normalize_presentation_payload(payload)
    return data
