"""Validar saldo de cuenta (conversación fresca)."""
from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
CID = f"bal-{uuid.uuid4().hex[:8]}"


def post(path: str, payload: dict, timeout: int = 60) -> dict:
    raw = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://{HOST}:8447{path}",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    print("conv", CID)
    print("CTX", post("/orch/context", {
        "customer_id": "TEST-QA-001",
        "allow_lab_fallback": True,
        "conversation_id": CID,
    })["status"])

    for q in [
        "cuales son mis productos?",
        "cual es el saldo de la cuenta de ahorros terminada en 63641?",
    ]:
        t0 = time.time()
        data = post("/orch/chat/front", {
            "question": q,
            "message": q,
            "customer_id": "TEST-QA-001",
            "client_id": "TEST-QA-001",
            "subject_token": "TEST-QA-001",
            "conversation_id": CID,
            "channel": {"type": "web", "entrypoint": "pruebas_simulator"},
        })
        dt = time.time() - t0
        app = data.get("app_channel") or {}
        reply = data.get("reply") or app.get("client_response") or data.get("error") or ""
        print("---")
        print("Q:", q)
        print("SECONDS", round(dt, 2), "core_skipped", data.get("core_skipped"), "error", data.get("error"))
        print("REPLY:", str(reply)[:280])


if __name__ == "__main__":
    main()
