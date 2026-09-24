"""Inspeccionar contrato /chat/front del mcp-bridge y URLs reales."""
from __future__ import annotations

import os
import shlex

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
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=120)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

    print("=== mcp .env values (host only) ===")
    print(run(
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "for line in Path('/opt/genesis/mcp-bridge/.env').read_text().splitlines():\n"
        "  if not line.strip() or line.strip().startswith('#'): continue\n"
        "  k,_,_,v=line.partition('=')\n"
        "  # mask secrets but show hosts\n"
        "  if 'KEY' in k.upper() or 'SECRET' in k.upper() or 'TOKEN' in k.upper():\n"
        "    print(f'{k}=***len={len(v)}')\n"
        "  else:\n"
        "    print(f'{k}={v}')\n"
        "PY",
        sudo=True,
    ))
    print("=== /chat/front handler ===")
    print(run("sed -n '1211,1280p' /opt/genesis/mcp-bridge/main.py"))
    print("=== build_cognitive_turn_payload ===")
    print(run("sed -n '120,200p' /opt/genesis/mcp-bridge/main.py"))
    print("=== health mcp ===")
    print(run("curl -sS -m 8 http://127.0.0.1:8080/health"))
    print("=== smoke chat/front mcp ===")
    print(run(
        "curl -sS -m 40 -X POST http://127.0.0.1:8080/chat/front "
        "-H 'Content-Type: application/json' "
        "-d '{\"question\":\"hola\",\"client_id\":\"TEST-QA-001\",\"conversation_id\":\"sim-orch-1\"}' | head -c 800; echo"
    ))
    print("=== nginx site ===")
    print(run("cat /etc/nginx/sites-enabled/genesis-azure-cognitive-gateway", sudo=True))
    print("=== external ports probe from vm ===")
    print(run("curl -sS -m 5 -o /dev/null -w '80=%{http_code}\\n' http://127.0.0.1/health; curl -sS -m 5 -o /dev/null -w '8443=%{http_code}\\n' -k https://127.0.0.1:8443/health; curl -sS -m 5 -o /dev/null -w '8080=%{http_code}\\n' http://127.0.0.1:8080/health"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
