"""Check orch 8080 hang and Foundry enablement on host."""
from __future__ import annotations

import json
import os
import shlex

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
PASSWORD = os.environ["SSH_DEPLOY_PASS"]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)


def run(cmd: str, *, sudo: bool = False) -> str:
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=90)
    if sudo:
        stdin.write(PASSWORD + "\n")
        stdin.flush()
    return (stdout.read() + stderr.read()).decode("utf-8", "replace")


print("=== curl orch with timing ===")
print(run("curl -sS -m 3 -v http://127.0.0.1:8080/health 2>&1 | tail -30", sudo=True)[-1500:])
print()
print("=== process 8080 ===")
print(run("ps -fp $(ss -lntp | awk '/:8080/{print}' | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | head -1) 2>/dev/null || ss -lntp | grep 8080", sudo=True)[-800:])
print()
print("=== foundry helpers ===")
print(
    run(
        "cd /opt/genesis-cognitive-8447/Genesis_v2 && .venv/bin/python -c "
        "'import os; from pathlib import Path;\n"
        "p=Path(\".env\");\n"
        "[os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39))) for line in p.read_text().splitlines() if line.strip() and not line.startswith(\"#\") and \"=\" in line for k,v in [line.split(\"=\",1)]];\n"
        "import genesis_cognitive.rag.foundry_kb_agent as m; print([x for x in dir(m) if \"foundry\" in x.lower() or \"ask_\" in x.lower() or \"enabled\" in x.lower()]); print(\"env\", os.getenv(\"GENESIS_FOUNDRY_KB_AGENT\")); print(\"endpoint\", (os.getenv(\"GENESIS_FOUNDRY_PROJECT_ENDPOINT\") or \"\")[:70])'",
        sudo=True,
    )[-2000:]
)
client.close()
