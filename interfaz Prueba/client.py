"""Cliente HTTP de la capa cognitiva Genesis (simula el App / orquestador)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_ENDPOINT = "http://127.0.0.1:8445"
DEFAULT_TIMEOUT = 120.0


class CognitiveClient:
    """Llama las APIs de chat de genesis-cognitive.

    En produccion el App no habla con el LLM: llama POST /turn.
    El orquestador reenvia question + customer_id + conversation_id.
    """

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any] | list[Any]]:
        url = f"{self.endpoint}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                parsed: dict[str, Any] | list[Any] = json.loads(body) if body else {}
                return resp.status, parsed
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"error": raw or str(exc)}
            return exc.code, parsed
        except urllib.error.URLError as exc:
            raise ConnectionError(f"No se pudo conectar a {url}: {exc.reason}") from exc

    def health(self) -> dict[str, Any]:
        status, body = self._request("GET", "/health")
        if status != 200 or not isinstance(body, dict):
            raise ConnectionError(f"Health HTTP {status}: {body}")
        return body

    def customers(self) -> list[dict[str, str]]:
        status, body = self._request("GET", "/customers")
        if status != 200:
            return []
        if isinstance(body, list):
            return body
        return []

    def turn(
        self,
        question: str | None,
        *,
        customer_id: str,
        conversation_id: str,
        force_core_query: bool = False,
        context_info: bool = False,
        context_op: str = "load",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Canal de produccion: App / orquestador → cognitiva."""
        payload: dict[str, Any] = {
            "question": question,
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "force_core_query": force_core_query,
        }
        if context_info:
            payload["context_info"] = True
            payload["context_op"] = context_op
            payload["context"] = context or {"data": {}}
        status, body = self._request("POST", "/turn", payload)
        if not isinstance(body, dict):
            raise RuntimeError(f"Respuesta inesperada HTTP {status}: {body}")
        body["_http_status"] = status
        return body

    def inspect(
        self,
        question: str,
        *,
        customer_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        """Canal de laboratorio: traza completa (intent, loan_detail, decision_trace)."""
        payload = {
            "question": question,
            "customer_id": customer_id,
            "conversation_id": conversation_id,
        }
        status, body = self._request("POST", "/inspect", payload)
        if not isinstance(body, dict):
            raise RuntimeError(f"Respuesta inesperada HTTP {status}: {body}")
        body["_http_status"] = status
        return body
