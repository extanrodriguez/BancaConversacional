"""Debug /orch/chat/front post-deploy."""
from __future__ import annotations

import os
import shlex
import uuid

import paramiko


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        os.environ.get("SSH_HOST", "20.127.25.24"),
        username=os.environ.get("SSH_USER", "genesis"),
        password=password,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )

    def run(cmd: str, *, sudo: bool = False) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

    cid = "dbg-" + uuid.uuid4().hex[:8]
    print("=== services ===")
    print(run("systemctl is-active genesis-mcp-bridge genesis-cognitive-8447; ss -tlnp | grep -E ':8080|:8447'"))
    print("=== mcp env cognitive ===")
    print(run("grep COGNITIVE_ /opt/genesis/mcp-bridge/.env"))
    print("=== login ===")
    print(run(
        f"curl -sS -m 20 -X POST http://127.0.0.1:8447/lab/login -H 'Content-Type: application/json' "
        f"-d '{{\"customer_id\":\"TEST-QA-001\",\"conversation_id\":\"{cid}\",\"portfolio\":\"qa_andres_david.json\"}}'"
    ))
    print("=== direct mcp ===")
    print(run(
        f"curl -sS -m 25 -w '\\nHTTP=%{{http_code}} time=%{{time_total}}\\n' -X POST http://127.0.0.1:8080/chat/front "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"question\":\"hola\",\"customer_id\":\"TEST-QA-001\",\"client_id\":\"TEST-QA-001\",\"subject_token\":\"TEST-QA-001\",\"conversation_id\":\"{cid}\"}}' | tail -c 500"
    ))
    print("=== via orch proxy ===")
    print(run(
        f"curl -sS -m 25 -w '\\nHTTP=%{{http_code}} time=%{{time_total}}\\n' -X POST http://127.0.0.1:8447/orch/chat/front "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"question\":\"hola\",\"customer_id\":\"TEST-QA-001\",\"client_id\":\"TEST-QA-001\",\"subject_token\":\"TEST-QA-001\",\"conversation_id\":\"{cid}\"}}' | tail -c 500"
    ))
    print("=== has route? ===")
    print(run("grep -n 'orch/chat/front' /opt/genesis-cognitive-8447/Genesis_v2/src/genesis_cognitive/demo/contract_inspector_app.py | head"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
