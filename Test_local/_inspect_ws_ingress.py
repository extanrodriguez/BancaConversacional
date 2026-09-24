"""Inspeccionar protocolo WS ingress en la VM."""
from __future__ import annotations

import os
import shlex

import paramiko

PASSWORD = os.environ["SSH_DEPLOY_PASS"]
HOST = os.environ.get("SSH_HOST", "20.127.25.24")


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="genesis", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    cmd = (
        "ls /opt/genesis/ws-ingress 2>/dev/null; "
        "wc -l /opt/genesis/ws-ingress/main.py 2>/dev/null; "
        "grep -nE 'customerId|websocket|context|products|accept|receive|send' "
        "/opt/genesis/ws-ingress/main.py 2>/dev/null | head -60"
    )
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = c.exec_command(wrapped, get_pty=True, timeout=60)
    stdin.write(PASSWORD + "\n")
    stdin.flush()
    print((stdout.read() + stderr.read()).decode("utf-8", errors="replace")[-8000:])
    c.close()


if __name__ == "__main__":
    main()
