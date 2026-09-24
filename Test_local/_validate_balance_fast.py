"""Validar que balance ya no cuelga ~45s."""
from __future__ import annotations

import json
import os
import time
import urllib.request

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
PASSWORD = os.environ["SSH_DEPLOY_PASS"]


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="genesis", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    for _ in range(10):
        stdin, stdout, stderr = client.exec_command(
            "systemctl is-active genesis-mcp-bridge; curl -sS -m 3 http://127.0.0.1:8080/health",
            timeout=20,
        )
        out = stdout.read().decode("utf-8", errors="replace")
        print(out.strip())
        if "active" in out and "Failed" not in out:
            break
        time.sleep(2)
    client.close()

    ctx = json.dumps(
        {"customer_id": "TEST-QA-001", "allow_lab_fallback": True, "conversation_id": "bal-fix-1"}
    ).encode()
    req = urllib.request.Request(
        f"http://{HOST}:8447/orch/context",
        data=ctx,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print("CTX", urllib.request.urlopen(req, timeout=30).read().decode()[:280])

    chat = json.dumps(
        {
            "question": "cual es el saldo de mi cuenta de ahorros terminada en 63641?",
            "message": "cual es el saldo de mi cuenta de ahorros terminada en 63641?",
            "customer_id": "TEST-QA-001",
            "client_id": "TEST-QA-001",
            "subject_token": "TEST-QA-001",
            "conversation_id": "bal-fix-1",
            "channel": {"type": "web", "entrypoint": "pruebas_simulator"},
        }
    ).encode()
    t0 = time.time()
    req = urllib.request.Request(
        f"http://{HOST}:8447/orch/chat/front",
        data=chat,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    raw = urllib.request.urlopen(req, timeout=90).read().decode()
    dt = time.time() - t0
    data = json.loads(raw)
    print("SECONDS", round(dt, 2))
    print("error", data.get("error"))
    print("core_skipped", data.get("core_skipped"), data.get("core_skip_reason"))
    app = data.get("app_channel") or {}
    print("status", data.get("status") or app.get("status"))
    reply = data.get("reply") or app.get("client_response") or ""
    print("reply", reply[:300])
    return 0 if dt < 20 and not data.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
