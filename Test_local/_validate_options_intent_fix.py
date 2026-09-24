"""Asegurar GENESIS_DISABLE_OPTIONS=0 y validar shape options+intent."""
from __future__ import annotations

import json
import os
import shlex
import uuid
import urllib.request

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
PASSWORD = os.environ["SSH_DEPLOY_PASS"]


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="genesis", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    cmd = (
        "ENV=/opt/genesis-cognitive-8447/Genesis_v2/.env; "
        "if grep -q '^GENESIS_DISABLE_OPTIONS=' \"$ENV\" 2>/dev/null; then "
        "sed -i 's/^GENESIS_DISABLE_OPTIONS=.*/GENESIS_DISABLE_OPTIONS=0/' \"$ENV\"; "
        "else echo 'GENESIS_DISABLE_OPTIONS=0' >> \"$ENV\"; fi; "
        "grep GENESIS_DISABLE_OPTIONS \"$ENV\"; "
        "systemctl restart genesis-cognitive-8447; sleep 2; systemctl is-active genesis-cognitive-8447"
    )
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = c.exec_command(wrapped, get_pty=True, timeout=60)
    stdin.write(PASSWORD + "\n")
    stdin.flush()
    print((stdout.read() + stderr.read()).decode("utf-8", errors="replace")[-1500:])
    c.close()

    cid = f"fix-{uuid.uuid4().hex[:6]}"

    def post(path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"http://{HOST}:8447{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())

    post("/orch/context", {"customer_id": "TEST-QA-001", "conversation_id": cid, "allow_lab_fallback": True})
    data = post(
        "/turn",
        {
            "question": "cual es el saldo de mi cuenta?",
            "customer_id": "TEST-QA-001",
            "conversation_id": cid,
        },
    )
    app = data.get("app_channel") or {}
    print("status", app.get("status"))
    print("intent_id", app.get("intent_id"))
    print("options_count", len(app.get("options") or []))
    print("options", json.dumps(app.get("options"), ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
