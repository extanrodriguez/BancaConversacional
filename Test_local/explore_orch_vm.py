"""Explorar orquestador/webhook/MCP en la VM (arquitectura de referencia)."""
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

    print("=== /opt/genesis ===")
    print(run("ls -la /opt/genesis 2>/dev/null; ls -la /opt/genesis/*/ 2>/dev/null | head -80"))
    print("=== listening ports ===")
    print(run("ss -tlnp | grep -E 'LISTEN' "))
    print("=== systemd genesis* ===")
    print(run("systemctl list-units --type=service --all | grep -iE 'genesis|mcp|orch|rag|ws|gateway' || true", sudo=True))
    print("=== search webhook/orch ===")
    print(run("find /opt/genesis /opt/genesis-rag -maxdepth 3 -type f \( -name '*.env' -o -name '*.yml' -o -name '*.yaml' -o -name 'README*' \) 2>/dev/null | head -80"))
    print("=== env hints ===")
    print(run("grep -RIlE 'webhook|orchestr|8447|/turn|CHAT_API|MCP' /opt/genesis /opt/genesis-rag 2>/dev/null | head -40"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
