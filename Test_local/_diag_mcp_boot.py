"""Diagnóstico fallo arranque MCP tras patch."""
from __future__ import annotations

import os
import shlex

import paramiko

PASSWORD = os.environ["SSH_DEPLOY_PASS"]
HOST = os.environ.get("SSH_HOST", "20.127.25.24")


def sudo(client, cmd: str) -> str:
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=60)
    stdin.write(PASSWORD + "\n")
    stdin.flush()
    return (stdout.read() + stderr.read()).decode("utf-8", errors="replace")


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="genesis", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    print(sudo(c, "systemctl status genesis-mcp-bridge --no-pager -l | tail -40"))
    print("=" * 40)
    print(sudo(c, "journalctl -u genesis-mcp-bridge -n 60 --no-pager"))
    print("=" * 40)
    print(sudo(c, "python3 -c \"import ast; ast.parse(open('/opt/genesis/mcp-bridge/main.py').read()); print('AST_OK')\""))
    print("=" * 40)
    # show helper insert region
    print(sudo(c, "sed -n '40,130p' /opt/genesis/mcp-bridge/main.py"))
    c.close()


if __name__ == "__main__":
    main()
