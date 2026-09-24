"""Alinea mcp-bridge (orquestador) a cognitiva 8447 y parchea client_id."""
from __future__ import annotations

import os
import shlex

import paramiko

ENV = """COGNITIVE_TURN_URL=http://127.0.0.1:8447/turn
COGNITIVE_LEGACY_CHAT_URL=http://127.0.0.1:8447/chat/front
COGNITIVE_RENDER_URL=http://127.0.0.1:8447/turn
COGNITIVE_HEALTH_URL=http://127.0.0.1:8447/health
COGNITIVE_FUNCTION_KEY=
CORE_OPERATIONS_URL=http://4.227.182.177:8090/core/v1/operations
CORE_HEALTH_URL=http://4.227.182.177:8090/core/health
"""

PATCH_PY = r'''
from pathlib import Path
import time
p = Path("/opt/genesis/mcp-bridge/main.py")
text = p.read_text(encoding="utf-8")
old = (
    "def get_customer_id(payload: Dict[str, Any]) -> str:\n"
    "    return payload.get(\"customer_id\") or payload.get(\"customerId\") or \"CUST001\""
)
new = (
    "def get_customer_id(payload: Dict[str, Any]) -> str:\n"
    "    return (\n"
    "        payload.get(\"customer_id\")\n"
    "        or payload.get(\"customerId\")\n"
    "        or payload.get(\"client_id\")\n"
    "        or payload.get(\"clientId\")\n"
    "        or \"CUST001\"\n"
    "    )"
)
if "payload.get(\"client_id\")" in text and "def get_customer_id" in text:
    print("already patched")
elif old not in text:
    raise SystemExit("get_customer_id block not found")
else:
    stamp = time.strftime("%Y%m%d%H%M%S")
    Path(f"/opt/genesis/mcp-bridge/main.py.bak.clientid.{stamp}").write_text(text, encoding="utf-8")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("patched get_customer_id")
'''


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

    print(run("cp -a /opt/genesis/mcp-bridge/.env /opt/genesis/mcp-bridge/.env.bak.$(date +%Y%m%d%H%M%S)", sudo=True))
    sftp = client.open_sftp()
    with sftp.file("/tmp/mcp-bridge.env", "w") as f:
        f.write(ENV)
    with sftp.file("/tmp/patch_mcp_clientid.py", "w") as f:
        f.write(PATCH_PY)
    sftp.close()
    print(run("cp /tmp/mcp-bridge.env /opt/genesis/mcp-bridge/.env && cat /opt/genesis/mcp-bridge/.env", sudo=True))
    print(run("python3 /tmp/patch_mcp_clientid.py", sudo=True))
    print(run("systemctl restart genesis-mcp-bridge && sleep 2 && systemctl is-active genesis-mcp-bridge", sudo=True))
    print("=== health ===")
    print(run("curl -sS -m 15 http://127.0.0.1:8080/health | head -c 600; echo"))
    print("=== smoke ===")
    print(
        run(
            "curl -sS -m 40 -X POST http://127.0.0.1:8080/chat/front "
            "-H 'Content-Type: application/json' "
            "-d '{\"question\":\"hola\",\"customer_id\":\"TEST-QA-001\",\"client_id\":\"TEST-QA-001\",\"conversation_id\":\"sim-orch-3\"}' "
            "| head -c 800; echo"
        )
    )
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
