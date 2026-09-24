"""Comparar path HTTP vs WebSocket para balance."""
from __future__ import annotations

import json
import os
import shlex
import uuid

import paramiko

PASSWORD = os.environ["SSH_DEPLOY_PASS"]
HOST = os.environ.get("SSH_HOST", "20.127.25.24")


def sudo(c, cmd: str) -> str:
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = c.exec_command(wrapped, get_pty=True, timeout=90)
    stdin.write(PASSWORD + "\n")
    stdin.flush()
    return (stdout.read() + stderr.read()).decode("utf-8", errors="replace")


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="genesis", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    print("=== ws-ingress full main.py ===")
    print(sudo(c, "sed -n '1,222p' /opt/genesis/ws-ingress/main.py"))
    print("=== services / ports ===")
    print(sudo(c, "systemctl list-units --type=service --state=running | grep -i genesis; ss -lntp | grep -E ':808|:844|:800|:900' || true"))
    print("=== ws-ingress env ===")
    print(sudo(c, "ls -la /opt/genesis/ws-ingress/; sed 's/=.*/=***/' /opt/genesis/ws-ingress/.env 2>/dev/null || true"))
    c.close()


if __name__ == "__main__":
    main()
