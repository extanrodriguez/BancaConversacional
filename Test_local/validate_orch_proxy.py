"""Valida simulador externo: login + /orch/chat/front (APK-like)."""
from __future__ import annotations

import json
import uuid
import urllib.request

BASE = "http://20.127.25.24:8447"


def call(path: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main() -> None:
    html = urllib.request.urlopen(BASE + "/pruebas/", timeout=20).read().decode("utf-8", "replace")
    print("ui_v8", "app.js?v=8" in html, "orquestador MCP" in html)
    cid = "ext-" + uuid.uuid4().hex[:8]
    login = call(
        "/lab/login",
        {
            "customer_id": "TEST-QA-001",
            "conversation_id": cid,
            "portfolio": "qa_andres_david.json",
        },
    )
    print("login", login.get("status"), login.get("customer_id"))
    hola = call(
        "/orch/chat/front",
        {
            "question": "hola",
            "customer_id": "TEST-QA-001",
            "client_id": "TEST-QA-001",
            "subject_token": "TEST-QA-001",
            "conversation_id": cid,
        },
    )
    print("hola", hola.get("status"), (hola.get("reply") or "")[:120])
    bal = call(
        "/orch/chat/front",
        {
            "question": "dame un balance de mis cuentas",
            "customer_id": "TEST-QA-001",
            "client_id": "TEST-QA-001",
            "subject_token": "TEST-QA-001",
            "conversation_id": cid,
        },
    )
    app = bal.get("app_channel") or {}
    print(
        "balance",
        bal.get("status") or app.get("status"),
        "opts",
        len(app.get("options") or bal.get("options") or []),
        (bal.get("reply") or app.get("client_response") or "")[:140],
    )


if __name__ == "__main__":
    main()
