"""Diagnóstico APK :8000 vs cognitiva 8447 en la VM."""
from __future__ import annotations

import json
import os
import shlex
import sys
import time

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
    client.connect(host, username=user, password=password, timeout=30, look_for_keys=False, allow_agent=False)

    def run(cmd: str, *, sudo: bool = False) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=120)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return (out + err).strip()

    print("=== ports ===")
    print(run("ss -tlnp | grep -E ':8000|:8447' || true"))
    print("=== services ===")
    print(run("systemctl is-active genesis-rag 2>/dev/null; systemctl is-active genesis-cognitive-8447 2>/dev/null; systemctl status genesis-rag --no-pager -l 2>/dev/null | head -40", sudo=True))
    print("=== proxy file ===")
    print(run("ls -la /opt/genesis-rag/app/cognitive_front_proxy.py 2>/dev/null; grep -n 'chat/front\\|proxy_to_cognitive\\|8447' /opt/genesis-rag/app/main.py 2>/dev/null | head -40"))
    print("=== local curls ===")
    print(run("curl -sS -m 5 http://127.0.0.1:8447/health; echo; curl -sS -m 5 http://127.0.0.1:8000/health; echo; curl -sS -m 8 -o /tmp/front_out.json -w 'http=%{http_code} time=%{time_total}\\n' -X POST 'http://127.0.0.1:8000/chat/front?x-api-key=test' -H 'Content-Type: application/json' -d '{\"message\":\"hola\",\"client_id\":\"TEST-QA-001\"}'; head -c 500 /tmp/front_out.json; echo"))
    print("=== recent rag logs ===")
    print(run("journalctl -u genesis-rag -n 40 --no-pager 2>/dev/null || journalctl -u rag -n 40 --no-pager 2>/dev/null || ls /opt/genesis-rag/", sudo=True))

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
