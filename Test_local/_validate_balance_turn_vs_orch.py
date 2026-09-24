"""Comparar /turn directo vs orch para saldo."""
from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
CID = f"turn-{uuid.uuid4().hex[:8]}"


def post(path: str, payload: dict) -> tuple[float, dict]:
    raw = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://{HOST}:8447{path}",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return time.time() - t0, data


def main() -> None:
    post("/orch/context", {
        "customer_id": "TEST-QA-001",
        "allow_lab_fallback": True,
        "conversation_id": CID,
    })
    q = "cual es el saldo de la cuenta de ahorros terminada en 63641?"
    dt, data = post("/turn", {
        "question": q,
        "customer_id": "TEST-QA-001",
        "conversation_id": CID,
        "force_core_query": False,
    })
    app = data.get("app_channel") or {}
    print("TURN", round(dt, 2), app.get("status"), (app.get("client_response") or "")[:220])

    cid2 = f"orch-{uuid.uuid4().hex[:8]}"
    post("/orch/context", {
        "customer_id": "TEST-QA-001",
        "allow_lab_fallback": True,
        "conversation_id": cid2,
    })
    # subject distinto para evitar pending MCP viejo
    subj = f"lab-{uuid.uuid4().hex[:8]}"
    dt, data = post("/orch/chat/front", {
        "question": q,
        "message": q,
        "customer_id": "TEST-QA-001",
        "client_id": "TEST-QA-001",
        "subject_token": subj,
        "conversation_id": cid2,
    })
    app = data.get("app_channel") or {}
    print(
        "ORCH",
        round(dt, 2),
        "skip",
        data.get("core_skipped"),
        data.get("error"),
        app.get("status") or data.get("status"),
        (data.get("reply") or app.get("client_response") or "")[:220],
    )


if __name__ == "__main__":
    main()
