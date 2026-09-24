"""Leer contratos del orquestador Genesis en la VM."""
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

    print("=== systemd unit files ===")
    print(run(
        "systemctl cat genesis-azure-cognitive-gateway.service genesis-mcp-bridge.service 2>/dev/null | head -120",
        sudo=True,
    ))
    print("=== gateway routes ===")
    print(run("grep -nE '@app\\.|APIRouter|include_router|/chat|/turn|webhook|client|orchestr' /opt/genesis/azure-cognitive-gateway/main.py | head -80"))
    print("=== mcp-bridge routes ===")
    print(run("grep -nE '@app\\.|APIRouter|/chat|/turn|webhook|context|core|cognitive|8447|8000' /opt/genesis/mcp-bridge/main.py | head -100"))
    print("=== ws-ingress routes ===")
    print(run("grep -nE '@app\\.|websocket|/chat|proxy|upstream' /opt/genesis/ws-ingress/main.py | head -80"))
    print("=== mcp .env masked ===")
    print(run("sed 's/=.*/=***/' /opt/genesis/mcp-bridge/.env"))
    print("=== which pid ports ===")
    print(run("ss -tlnp | grep -E ':8080|:8081|:8443|:80|:9000|:8445'"))
    print("=== nginx/caddy? ===")
    print(run("ls /etc/nginx/sites-enabled 2>/dev/null; grep -RInE 'proxy_pass|8000|8080|8447|chat' /etc/nginx 2>/dev/null | head -40", sudo=True))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
