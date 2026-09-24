"""Ver estado MCP y si el patch v2 está activo; ver pending sessions."""
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
    print(sudo(c, "systemctl is-active genesis-mcp-bridge; ss -lntp | grep -E ':8080|:8447|:8000' || true"))
    print("=" * 40)
    print(sudo(c, "grep -n 'cognitive_already_answered\\|CORE_OPS_TIMEOUT\\|core_skipped' /opt/genesis/mcp-bridge/main.py | head -40"))
    print("=" * 40)
    print(sudo(c, "grep -n 'CORE_OPERATIONS_URL\\|8090\\|timeout' /opt/genesis/mcp-bridge/.env /opt/genesis/mcp-bridge/main.py | head -30"))
    # recent MCP access around balance
    print("=" * 40)
    print(sudo(c, "journalctl -u genesis-mcp-bridge -n 30 --no-pager"))
    c.close()


if __name__ == "__main__":
    main()
