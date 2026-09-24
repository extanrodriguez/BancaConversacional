"""Diagnóstico: origen de core_operation_failed en la VM."""
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
    "grep -R 'core_operation_failed' /opt/genesis/mcp-bridge -n 2>/dev/null | head -50",
    "grep -R 'core_operation_failed' /opt/genesis-cognitive-8447 -n 2>/dev/null | head -50",
    "systemctl is-active genesis-mcp-bridge || true",
    "ss -lntp 2>/dev/null | grep -E ':8080|:8447|:8090' || true",
    "journalctl -u genesis-mcp-bridge -n 80 --no-pager 2>/dev/null || true",
    "ls /opt/genesis/mcp-bridge 2>/dev/null | head -40",
]

for cmd in cmds:
    print("=" * 60)
    print(cmd)
    stdin, stdout, stderr = client.exec_command(cmd, timeout=90)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out[-6000:] if out else "(empty)")
    if err.strip():
        print("STDERR:", err[-1500:])

client.close()
