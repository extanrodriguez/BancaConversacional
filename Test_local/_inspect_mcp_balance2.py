"""Extraer funciones clave del MCP bridge."""
from __future__ import annotations

import os
import sys

import paramiko

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

cmds = [
    "grep -n 'CORE_OPERATIONS_URL\\|def call_json\\|def call_cognitive\\|def build_cognitive\\|def cognitive_response_to_operation\\|def extract_operation_request\\|force_core' /opt/genesis/mcp-bridge/main.py | head -60",
    "sed -n '1,120p' /opt/genesis/mcp-bridge/main.py",
    "sed -n '300,420p' /opt/genesis/mcp-bridge/main.py",
    "sed -n '820,950p' /opt/genesis/mcp-bridge/main.py",
    "python3 - <<'PY'\nimport re\np=open('/opt/genesis/mcp-bridge/main.py',encoding='utf-8',errors='replace').read()\nfor name in ['cognitive_response_to_operation_request','extract_operation_request','build_cognitive_turn_payload','call_cognitive_turn']:\n m=re.search(rf'def {name}\\(.*?(?=\\ndef )',p,re.S)\n print('====',name)\n print(m.group(0)[:2500] if m else 'NOT FOUND')\nPY",
]

for cmd in cmds:
    print("=" * 60)
    stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
    print(stdout.read().decode("utf-8", errors="replace")[-9000:])
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", err[-1000:])

client.close()
