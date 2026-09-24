"""Inspeccionar MCP bridge: timeout y path de BALANCE."""
from __future__ import annotations

import os
import sys

import paramiko

host = os.environ.get("SSH_HOST", "20.127.25.24")
user = os.environ.get("SSH_USER", "genesis")
password = os.environ.get("SSH_DEPLOY_PASS")
if not password:
    print("ERROR: SSH_DEPLOY_PASS missing")
    sys.exit(1)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=password, timeout=30, look_for_keys=False, allow_agent=False)

cmds = [
    "grep -n '8090\\|timeout\\|BALANCE\\|core/v1\\|CORE_OPS\\|ConnectTimeout\\|urlopen\\|httpx\\|requests' /opt/genesis/mcp-bridge/main.py | head -80",
    "sed -n '680,780p' /opt/genesis/mcp-bridge/main.py",
    "sed -n '1180,1310p' /opt/genesis/mcp-bridge/main.py",
    "sed -n '1880,2030p' /opt/genesis/mcp-bridge/main.py",
    "ls -la /opt/genesis/mcp-bridge/.env 2>/dev/null; cat /opt/genesis/mcp-bridge/.env 2>/dev/null | sed 's/=.*/=***/'",
]

for cmd in cmds:
    print("=" * 60)
    print(cmd[:100])
    stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out[-8000:] if out else "(empty)")
    if err.strip():
        print("STDERR:", err[-800:])

client.close()
