"""Simula el orquestador: carga portafolio Core y llama POST /turn."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
PORTFOLIOS = HERE / "data" / "portfolios"
DEFAULT_ENDPOINT = "http://127.0.0.1:8445"


def _http(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 120.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"error": raw or str(exc)}
        parsed["_http_status"] = exc.code
        return parsed
    except URLError as exc:
        raise ConnectionError(f"No hay cognitiva en {url}: {exc.reason}") from exc


def load_portfolio(name: str) -> dict[str, Any]:
    path = PORTFOLIOS / name
    return json.loads(path.read_text(encoding="utf-8"))


def to_context_data(envelope: dict[str, Any]) -> dict[str, Any]:
    """Normaliza el JSON de Core al objeto que espera context.data."""
    products = envelope.get("data")
    if not isinstance(products, list):
        products = envelope.get("products") or []
    return {
        "primerNombre": envelope.get("primerNombre") or "Cliente",
        "products": products,
    }


class OrquestadorLocal:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, customer_id: str = "CUST_LOCAL") -> None:
        self.endpoint = endpoint.rstrip("/")
        self.customer_id = customer_id
        self.conversation_id = str(uuid.uuid4())

    def nueva_sesion(self) -> None:
        self.conversation_id = str(uuid.uuid4())

    def health(self) -> dict[str, Any]:
        return _http("GET", f"{self.endpoint}/health")

    def cargar_portafolio(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "question": None,
            "customer_id": self.customer_id,
            "conversation_id": self.conversation_id,
            "context_info": True,
            "context_op": "load",
            "context": {"data": to_context_data(envelope)},
        }
        return _http("POST", f"{self.endpoint}/turn", payload)

    def preguntar(self, question: str, *, force_core_query: bool = False) -> dict[str, Any]:
        payload = {
            "question": question,
            "customer_id": self.customer_id,
            "conversation_id": self.conversation_id,
            "force_core_query": force_core_query,
        }
        return _http("POST", f"{self.endpoint}/turn", payload)

    def inspeccionar(self, question: str) -> dict[str, Any]:
        payload = {
            "question": question,
            "customer_id": self.customer_id,
            "conversation_id": self.conversation_id,
        }
        return _http("POST", f"{self.endpoint}/inspect", payload)
