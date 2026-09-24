"""Leer .env MCP, reiniciar si hace falta y alinear cognitiva a 8447."""
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
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

    print("=== raw env ===")
    print(run("cat /opt/genesis/mcp-bridge/.env", sudo=True))
    print("=== mcp status ===")
    print(run("systemctl status genesis-mcp-bridge --no-pager -l | head -40", sudo=True))
    print("=== recent mcp logs ===")
    print(run("journalctl -u genesis-mcp-bridge -n 30 --no-pager", sudo=True))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
