"""Deep connectivity follow-up for :8447 (ports, Foundry live, Core DNS)."""
from __future__ import annotations

import json
import os
import shlex
import sys
import urllib.request

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
PASSWORD = os.environ.get("SSH_DEPLOY_PASS")
REMOTE = "/tmp/audit_8447_deep.py"


def main() -> int:
    if not PASSWORD:
        print("ERROR: SSH_DEPLOY_PASS missing")
        return 1

    remote = r'''
import json, os, socket, urllib.request
from pathlib import Path

out = {}

# ports
try:
    import subprocess
    p = subprocess.run(["ss", "-lntp"], capture_output=True, text=True, timeout=10)
    lines = [ln for ln in (p.stdout or "").splitlines() if any(x in ln for x in (":8080", ":8447", ":8446"))]
    out["listen"] = lines[:20]
except Exception as e:
    out["listen"] = str(e)

# systemd
try:
    import subprocess
    p = subprocess.run(
        ["systemctl", "is-active", "genesis-cognitive-8447.service"],
        capture_output=True, text=True, timeout=10,
    )
    out["systemd_8447"] = (p.stdout or p.stderr or "").strip()
except Exception as e:
    out["systemd_8447"] = str(e)

# curl orch 8080
for label, url in [
    ("orch_8080", "http://127.0.0.1:8080/health"),
    ("orch_via_8447", "http://127.0.0.1:8447/orch/health"),
]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            out[label] = {"http": resp.status, "body": resp.read().decode()[:200]}
    except Exception as e:
        out[label] = {"error": str(e)}

# DNS
for host in [
    "api-genesis.dev.bsc.com.do",
    "foundry-bsc-genesis-dev.services.ai.azure.com",
    "ai-search-genesis.search.windows.net",
    "testbsc0001.openai.azure.com",
]:
    try:
        out.setdefault("dns", {})[host] = socket.getaddrinfo(host, 443)[0][4][0]
    except Exception as e:
        out.setdefault("dns", {})[host] = f"FAIL:{e}"

# Foundry live
os.chdir("/opt/genesis-cognitive-8447/Genesis_v2")
# load .env into process if present
envp = Path(".env")
if envp.is_file():
    for line in envp.read_text(encoding="utf-8", errors="replace").splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k,v=line.split("=",1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

try:
    from genesis_cognitive.rag.foundry_kb_agent import foundry_kb_agent_enabled, ask_foundry_kb_agent
    enabled = foundry_kb_agent_enabled()
    r = ask_foundry_kb_agent("requisitos para abrir cuenta de ahorro", display_name="Audit")
    if isinstance(r, dict):
        out["foundry_live"] = {
            "enabled": enabled,
            "keys": list(r.keys()),
            "status": r.get("status"),
            "reply": str(r.get("reply") or r.get("answer") or r.get("message") or "")[:240],
        }
    else:
        out["foundry_live"] = {"enabled": enabled, "raw": str(r)[:240]}
except Exception as e:
    out["foundry_live"] = {"error": str(e)}

print(json.dumps(out, ensure_ascii=False, indent=2))
'''

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    with sftp.file(REMOTE, "w") as f:
        f.write(remote)
    sftp.close()

    def run(cmd: str, *, sudo: bool = False) -> tuple[int, str]:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
        if sudo:
            stdin.write(PASSWORD + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return stdout.channel.recv_exit_status(), (out + err).strip()

    # use venv python for foundry imports
    code, text = run(
        f"cd /opt/genesis-cognitive-8447/Genesis_v2 && .venv/bin/python {REMOTE}",
        sudo=True,
    )
    client.close()
    start, end = text.find("{"), text.rfind("}")
    if start < 0:
        print(text[-3000:])
        return 1
    data = json.loads(text[start : end + 1])
    print(json.dumps(data, ensure_ascii=False, indent=2))

    # also probe webhook session context_source from outside
    print("\n=== WEBHOOK SESSION context_source ===")
    try:
        req = urllib.request.Request(
            f"http://{HOST}:8447/orch/webhook/session",
            data=json.dumps({"allow_lab_fallback": True}).encode(),
            headers={"Content-Type": "application/json", "ClientId": "726588"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
        print(json.dumps({
            "status": body.get("status"),
            "context_source": body.get("context_source"),
            "display_name": body.get("display_name"),
            "customer_id": body.get("customer_id"),
        }, ensure_ascii=False, indent=2))
    except Exception as e:
        print("FAIL", e)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
