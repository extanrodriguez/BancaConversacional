"""Audit :8447 remote env — mocks, connectivity (secrets redacted)."""
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
ENV_PATH = "/opt/genesis-cognitive-8447/Genesis_v2/.env"
REMOTE_PY = "/tmp/audit_8447_env.py"


def main() -> int:
    if not PASSWORD:
        print("ERROR: SSH_DEPLOY_PASS missing")
        return 1

    remote_script = r'''
from pathlib import Path
import json, re, urllib.request, os, socket

ENV = Path("/opt/genesis-cognitive-8447/Genesis_v2/.env")
out = {"checks": [], "env": {}, "mock_like": [], "connectivity": {}}

def add(name, ok, detail=""):
    out["checks"].append({"name": name, "ok": bool(ok), "detail": detail})

raw = ENV.read_text(encoding="utf-8", errors="replace") if ENV.is_file() else ""
vals = {}
for line in raw.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    vals[k.strip()] = v.strip().strip('"').strip("'")

keys = [
    "GENESIS_ENV", "GENESIS_HOST", "GENESIS_PORT", "GENESIS_SQLITE_PATH",
    "GENESIS_FOUNDRY_KB_AGENT", "GENESIS_FOUNDRY_PROJECT_ENDPOINT",
    "GENESIS_FOUNDRY_KB_AGENT_NAME", "GENESIS_FOUNDRY_KB_AGENT_VERSION",
    "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_INDEX",
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "GENESIS_CORE_CONTEXT_URL", "GENESIS_ORCH_URL",
    "GENESIS_FAQ_PATH", "GENESIS_FAQ_OVERLAY_PATH",
    "GENESIS_KB_CONFIDENCE_GATE", "GENESIS_FOUNDRY_CACHE",
]
for k in keys:
    out["env"][k] = vals.get(k, "(unset)")

for k, v in vals.items():
    kl, vl = k.lower(), v.lower()
    if any(s in kl for s in ("mock", "fake", "stub", "dummy")) or any(
        s in vl for s in ("mock", "fake", "stub://", "localhost/mock", "http://mock")
    ):
        out["mock_like"].append(f"{k}={v}")

add("env_file_exists", ENV.is_file(), str(ENV))
add("no_mock_flags", len(out["mock_like"]) == 0, ", ".join(out["mock_like"]) or "none")
add("foundry_enabled", vals.get("GENESIS_FOUNDRY_KB_AGENT", "").lower() in ("1", "true", "yes", "on"), vals.get("GENESIS_FOUNDRY_KB_AGENT"))
add("foundry_endpoint_real", "foundry" in vals.get("GENESIS_FOUNDRY_PROJECT_ENDPOINT", "").lower() and "http" in vals.get("GENESIS_FOUNDRY_PROJECT_ENDPOINT", "").lower(), vals.get("GENESIS_FOUNDRY_PROJECT_ENDPOINT", "")[:80])
add("search_index_real", vals.get("AZURE_SEARCH_INDEX") == "bsc-kb-conocimiento", vals.get("AZURE_SEARCH_INDEX"))
add("search_endpoint_real", "search.windows.net" in vals.get("AZURE_SEARCH_ENDPOINT", ""), vals.get("AZURE_SEARCH_ENDPOINT", "")[:80])
add("openai_endpoint_real", "openai.azure.com" in vals.get("AZURE_OPENAI_ENDPOINT", ""), vals.get("AZURE_OPENAI_ENDPOINT", "")[:80])
add("has_search_key", bool(vals.get("AZURE_SEARCH_API_KEY")), "set" if vals.get("AZURE_SEARCH_API_KEY") else "missing")
add("has_openai_key", bool(vals.get("AZURE_OPENAI_API_KEY") or vals.get("OPENAI_API_KEY")), "set" if (vals.get("AZURE_OPENAI_API_KEY") or vals.get("OPENAI_API_KEY")) else "missing")
add("port_8447", vals.get("GENESIS_PORT") == "8447", vals.get("GENESIS_PORT"))
add("host_0_0_0_0", vals.get("GENESIS_HOST") == "0.0.0.0", vals.get("GENESIS_HOST"))

# health
for label, url in [
    ("health_loopback", "http://127.0.0.1:8447/health"),
    ("health_private", "http://192.168.150.5:8447/health"),
    ("orch_health", "http://127.0.0.1:8447/orch/health"),
]:
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            out["connectivity"][label] = {"http": resp.status, "body": body[:300]}
            add(label, resp.status == 200, body[:180])
    except Exception as e:
        out["connectivity"][label] = {"error": str(e)}
        add(label, False, str(e))

# DNS / TCP reachability to Azure endpoints (no secrets)
for name, host, port in [
    ("tcp_openai", vals.get("AZURE_OPENAI_ENDPOINT", "").replace("https://", "").split("/")[0], 443),
    ("tcp_search", vals.get("AZURE_SEARCH_ENDPOINT", "").replace("https://", "").split("/")[0], 443),
    ("tcp_foundry", vals.get("GENESIS_FOUNDRY_PROJECT_ENDPOINT", "").replace("https://", "").split("/")[0], 443),
]:
    if not host:
        add(name, False, "unset")
        continue
    try:
        socket.create_connection((host, port), timeout=8).close()
        add(name, True, f"{host}:{port}")
        out["connectivity"][name] = "ok"
    except Exception as e:
        add(name, False, f"{host}:{port} {e}")
        out["connectivity"][name] = str(e)

# Core WS URL host
core = vals.get("GENESIS_CORE_CONTEXT_URL") or "https://api-genesis.dev.bsc.com.do/ws/"
core_host = core.replace("https://", "").replace("http://", "").split("/")[0]
try:
    socket.create_connection((core_host, 443), timeout=8).close()
    add("tcp_core_ws", True, core_host)
except Exception as e:
    add("tcp_core_ws", False, f"{core_host} {e}")

# Azure Search simple query (if key present)
search_ep = vals.get("AZURE_SEARCH_ENDPOINT", "").rstrip("/")
search_idx = vals.get("AZURE_SEARCH_INDEX", "")
search_key = vals.get("AZURE_SEARCH_API_KEY", "")
if search_ep and search_idx and search_key:
    url = f"{search_ep}/indexes/{search_idx}/docs/$count?api-version=2024-07-01"
    req = urllib.request.Request(url, headers={"api-key": search_key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            cnt = resp.read().decode("utf-8", errors="replace").strip()
            add("azure_search_count", resp.status == 200 and cnt.isdigit(), f"docs={cnt}")
            out["connectivity"]["azure_search_docs"] = cnt
    except Exception as e:
        add("azure_search_count", False, str(e)[:200])
else:
    add("azure_search_count", False, "missing endpoint/index/key")

# FAQ files
faq = Path(vals.get("GENESIS_FAQ_PATH", ""))
ovl = Path(vals.get("GENESIS_FAQ_OVERLAY_PATH", ""))
add("faq_file", faq.is_file(), str(faq))
add("faq_overlay_file", ovl.is_file(), str(ovl))

print(json.dumps(out, ensure_ascii=False, indent=2))
'''

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"SSH {USER}@{HOST}...")
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    with sftp.file(REMOTE_PY, "w") as f:
        f.write(remote_script)
    sftp.close()

    def run(cmd: str, *, sudo: bool = False) -> tuple[int, str]:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
        if sudo:
            stdin.write(PASSWORD + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, (out + err).strip()

    code, text = run(f"python3 {REMOTE_PY}", sudo=True)
    client.close()

    # Extract JSON from output (skip sudo noise)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        print("RAW_OUTPUT:")
        print(text[-4000:])
        return 1
    data = json.loads(text[start : end + 1])

    print("=== ENV (sin secretos) ===")
    for k, v in data.get("env", {}).items():
        print(f"  {k}={v}")
    print()
    print("=== MOCK-LIKE ===")
    print("  ", data.get("mock_like") or "NONE")
    print()
    print("=== CHECKS ===")
    fails = 0
    for c in data.get("checks", []):
        mark = "PASS" if c["ok"] else "FAIL"
        if not c["ok"]:
            fails += 1
        detail = (c.get("detail") or "")[:160]
        print(f"  {mark}  {c['name']}: {detail}")
    print()
    print(f"Resultado: {len(data.get('checks', [])) - fails} PASS / {fails} FAIL")

    # Public health from outside
    print()
    print("=== PUBLIC HEALTH ===")
    try:
        with urllib.request.urlopen(f"http://{HOST}:8447/health", timeout=10) as resp:
            print(" ", resp.status, resp.read().decode()[:200])
    except Exception as e:
        print("  FAIL", e)
        fails += 1

    # Live Foundry via inspect knowledge question
    print()
    print("=== LIVE FOUNDRY/KB PATH ===")
    try:
        body = json.dumps({
            "question": "que es un certificado de deposito",
            "customer_id": "323677",
            "conversation_id": "audit-8447-kb",
        }).encode()
        req = urllib.request.Request(
            f"http://{HOST}:8447/inspect",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            r = json.loads(resp.read().decode())
        reply = (r.get("client_response") or "")[:180].replace("\n", " ")
        rag = r.get("rag_status")
        steps = [x.get("step") for x in (r.get("decision_trace") or []) if isinstance(x, dict)][:4]
        print(f"  status={r.get('status')} rag={rag} steps={steps}")
        print(f"  reply={reply}")
        # Should not look like mock placeholder
        mockish = any(s in reply.lower() for s in ("mock", "lorem ipsum", "placeholder", "TODO"))
        if mockish or not reply:
            print("  FAIL reply empty/mockish")
            fails += 1
        else:
            print("  PASS knowledge path answered")
    except Exception as e:
        print("  FAIL", e)
        fails += 1

    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
