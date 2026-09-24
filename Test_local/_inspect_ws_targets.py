"""Ver a dónde apunta WS y gateway vs 8447."""
from __future__ import annotations

import os
import shlex

import paramiko

PASSWORD = os.environ["SSH_DEPLOY_PASS"]
HOST = os.environ.get("SSH_HOST", "20.127.25.24")


def sudo(c, cmd: str) -> str:
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = c.exec_command(wrapped, get_pty=True, timeout=60)
    stdin.write(PASSWORD + "\n")
    stdin.flush()
    return (stdout.read() + stderr.read()).decode("utf-8", errors="replace")


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="genesis", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    cmds = [
        "systemctl cat genesis-azure-cognitive-gateway.service 2>/dev/null | head -40",
        "grep -RInE 'ws|8447|8000|8080|FUNCTION|COGNITIVE|proxy' /etc/nginx/ 2>/dev/null | head -50",
        "find /opt/genesis -name '.env' 2>/dev/null | head -20",
        "for f in /opt/genesis/ws-ingress/.env /opt/genesis/azure-cognitive-gateway/.env /opt/genesis/mcp-bridge/.env; do echo ==== $f; sed 's/=.*/=***/' $f 2>/dev/null; done",
        "ss -lntp | grep -E '9000|8448|8443' ; curl -sS -m 3 http://127.0.0.1:9000/health 2>/dev/null || true; curl -sS -m 3 http://127.0.0.1:8448/health 2>/dev/null || true",
        "grep -nE 'customer_id|force_core|context_info|BALANCE|8090' /opt/genesis/azure-cognitive-gateway/main.py 2>/dev/null | head -40",
    ]
    for cmd in cmds:
        print("=" * 50, cmd[:70])
        print(sudo(c, cmd)[-3500:])
    c.close()


if __name__ == "__main__":
    main()
