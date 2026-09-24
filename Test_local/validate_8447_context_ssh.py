"""Validacion post-deploy 8447 via SSH (health + contexto/webhook)."""
from __future__ import annotations

import json
import os
import sys

import paramiko


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    if not password:
        print("ERROR: SSH_DEPLOY_PASS")
        return 1
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=user,
        password=password,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )

    def run(cmd: str, timeout: int = 120) -> str:
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return (out + err).strip()

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))
        print(("PASS" if ok else "FAIL"), "-", name)
        print(detail[:900])
        print("---")

    health = run("curl -sS -m 5 http://127.0.0.1:8447/health")
    check("health", '"status":"ok"' in health, health)

    pruebas = run("curl -sS -m 5 -o /dev/null -w %{http_code} http://127.0.0.1:8447/pruebas/")
    check("pruebas", pruebas.strip() == "200", pruebas)

    orch_h = run("curl -sS -m 8 http://127.0.0.1:8447/orch/health || true")
    check("orch_health", "Not Found" not in orch_h and len(orch_h) > 0, orch_h)

    session = run(
        "curl -sS -m 60 -X POST http://127.0.0.1:8447/orch/webhook/session "
        "-H 'Content-Type: application/json' -H 'ClientId: 726588' "
        "-d '{\"allow_lab_fallback\":true}'"
    )
    check(
        "webhook_session",
        ("conversation_id" in session or "CONTEXT" in session or "SESSION" in session)
        and "Not Found" not in session,
        session,
    )

    chat = run(
        "curl -sS -m 90 -X POST http://127.0.0.1:8447/orch/webhook/chat "
        "-H 'Content-Type: application/json' -H 'ClientId: 726588' "
        "-d '{\"question\":\"hola\"}'"
    )
    cid = None
    try:
        cid = json.loads(chat).get("conversation_id")
    except Exception:
        pass
    check(
        "webhook_chat",
        "reply" in chat and "conversation_id" in chat and "Not Found" not in chat,
        chat,
    )

    if cid:
        mt = run(
            "curl -sS -m 90 -X POST http://127.0.0.1:8447/orch/webhook/chat "
            "-H 'Content-Type: application/json' -H 'ClientId: 726588' "
            f"-H 'X-Conversation-Id: {cid}' "
            "-d '{\"question\":\"cuales son mis prestamos\"}'"
        )
        check(
            "webhook_multiturn_prestamos",
            "reply" in mt and "Not Found" not in mt,
            mt,
        )
    else:
        check("webhook_multiturn_prestamos", False, "sin conversation_id")

    ctx = run(
        "curl -sS -m 60 -X POST http://127.0.0.1:8447/orch/context "
        "-H 'Content-Type: application/json' "
        "-d '{\"customer_id\":\"726588\",\"allow_lab_fallback\":true}'"
    )
    check(
        "orch_context",
        "Not Found" not in ctx
        and (
            "display_name" in ctx
            or "CONTEXT" in ctx
            or "customer" in ctx.lower()
            or "status" in ctx
        ),
        ctx,
    )

    client.close()
    print("\n==== RESUMEN ====")
    for name, ok, _ in checks:
        print(("PASS" if ok else "FAIL"), name)
    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"TOTAL_PASS {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 2


if __name__ == "__main__":
    raise SystemExit(main())
