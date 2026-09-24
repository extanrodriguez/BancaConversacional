"""Proxy APK /chat/front -> cognitiva 8447 (respuesta con reply)."""
from __future__ import annotations

import json
import time
import uuid
import urllib.error
import urllib.request
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel

COGNITIVE_BASE = "http://127.0.0.1:8447"
_LOADED: set[str] = set()

_DEFAULT_PORTFOLIO: dict[str, Any] = {
    "primerNombre": "usuario 1",
    "products": [
        {
            "productCategory": "CA",
            "productIdentification": "11042010152142",
            "productDescription": "Cuenta de Ahorros",
            "currencyCode": "214",
            "productStatus": "3",
            "availableBalance": 5267.58,
            "currentBalance": 5267.58,
        },
        {
            "productCategory": "CA",
            "productIdentification": "21042020016468",
            "productDescription": "Cuenta de Ahorros",
            "currencyCode": "840",
            "productStatus": "3",
            "availableBalance": 0.24,
            "currentBalance": 0.24,
        },
        {
            "productCategory": "CA",
            "productIdentification": "11042020007731",
            "productDescription": "Cuenta Corriente",
            "currencyCode": "214",
            "productStatus": "3",
            "availableBalance": 18250.0,
            "currentBalance": 18250.0,
        },
        {
            "productCategory": "TC",
            "productIdentification": "250925031840000011",
            "productDescription": "Visa Bravo Santa Cruz",
            "currencyCode": "214",
            "productStatus": "1",
            "availableBalance": 83876.9,
            "availablePurchasesDomestic": 83876.9,
            "maskedCardNumber": "****9147",
        },
        {
            "productCategory": "TC",
            "productIdentification": "220710021030100868",
            "productDescription": "Visa Full Car",
            "currencyCode": "214",
            "productStatus": "1",
            "availableBalance": 5052.43,
            "availablePurchasesDomestic": 5052.43,
            "maskedCardNumber": "****6582",
        },
    ],
}


class FrontChatRequest(BaseModel):
    question: str = ""
    conversation_id: Optional[str] = None
    client_id: Optional[str] = None
    top_k: Optional[int] = 3
    # Alias usados por builds APK / clientes front
    message: Optional[str] = None
    content: Optional[str] = None
    text: Optional[str] = None

    def resolved_question(self) -> str:
        for value in (self.question, self.message, self.content, self.text):
            if value and str(value).strip():
                return str(value).strip()
        return ""


def _http_json(method: str, url: str, payload: dict | None = None, timeout: float = 25.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"error": raw or str(exc)}
        parsed["_http_status"] = exc.code
        return parsed


def ensure_cognitive_context(conversation_id: str, customer_id: str) -> None:
    key = f"{conversation_id}:{customer_id}"
    if key in _LOADED:
        return
    payload = {
        "question": None,
        "customer_id": customer_id,
        "conversation_id": conversation_id,
        "context_info": True,
        "context_op": "load",
        "context": {"data": _DEFAULT_PORTFOLIO},
    }
    res = _http_json("POST", f"{COGNITIVE_BASE}/turn", payload, timeout=15)
    if res.get("_http_status") and int(res["_http_status"]) >= 400:
        raise HTTPException(status_code=502, detail=f"No se pudo cargar contexto cognitivo: {res}")
    _LOADED.add(key)


def proxy_to_cognitive(payload: FrontChatRequest) -> dict:
    start = time.time()
    conversation_id = payload.conversation_id or f"conv_{uuid.uuid4().hex[:10]}"
    customer_id = (payload.client_id or "USUARIO1").strip() or "USUARIO1"
    question = payload.resolved_question()
    if not question:
        raise HTTPException(status_code=422, detail="question/message es obligatorio")
    ensure_cognitive_context(conversation_id, customer_id)
    turn = _http_json(
        "POST",
        f"{COGNITIVE_BASE}/turn",
        {
            "question": question,
            "conversation_id": conversation_id,
            "customer_id": customer_id,
            "client_id": customer_id,
            "top_k": payload.top_k or 3,
        },
        timeout=25,
    )
    if turn.get("_http_status") and int(turn["_http_status"]) >= 400:
        raise HTTPException(status_code=502, detail=turn)

    app = turn.get("app_channel") or {}
    reply = (
        (turn.get("reply") or "").strip()
        or (app.get("client_response") or "").strip()
        or (turn.get("message") or "").strip()
    )
    if not reply:
        raise HTTPException(status_code=502, detail="Cognitiva sin reply")

    return {
        "reply": reply,
        "conversation_id": app.get("conversation_id") or conversation_id,
        "status": app.get("status") or turn.get("status"),
        "intent": app.get("intent_id") or "unknown",
        "options": app.get("options") or [],
        "app_channel": app,
        "intent_category": "informativa",
        "is_transactional": False,
        "execution_allowed": False,
        "requires_authentication": False,
        "requires_confirmation": False,
        "handoff_required": False,
        "risk_level": "low",
        "next_action": "continue",
        "latency_ms": int((time.time() - start) * 1000),
    }
