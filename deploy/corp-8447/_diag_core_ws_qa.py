"""Diagnóstico Core WS desde host QA (sin secretos)."""
from __future__ import annotations

import json
import os
import shlex
import time
from pathlib import Path

import paramiko

REMOTE = r'''
import json, socket, urllib.request
from pathlib import Path
from urllib.parse import urlparse

env = {}
for line in Path("/opt/genesis-cognitive-8447/Genesis_v2/.env").read_text(errors="replace").splitlines():
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        continue
    k, v = s.split("=", 1)
    env[k] = v.strip().strip('"').strip("'")

url = env.get("GENESIS_CORE_CONTEXT_URL") or "https://api-genesis.dev.bsc.com.do/ws/"
print("CORE_URL", url)
u = urlparse(url.replace("wss://", "https://").replace("ws://", "http://"))
host, port = u.hostname, u.port or 443
print("HOST", host, "PORT", port)
try:
    ips = sorted({i[4][0] for i in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    print("DNS", ips[:5])
except Exception as e:
    print("DNS_ERR", type(e).__name__, e)

try:
    s = socket.create_connection((host, port), timeout=8)
    print("TCP_OK")
    s.close()
except Exception as e:
    print("TCP_ERR", type(e).__name__, str(e)[:150])

get_url = url.replace("wss://", "https://").replace("ws://", "http://")
if not get_url.endswith("/") and "?" not in get_url:
    get_url += "/"
sep = "&" if "?" in get_url else "?"
get_url = f"{get_url}{sep}customerId=726588"
print("GET_PATH", get_url.split("?")[0])
try:
    req = urllib.request.Request(get_url, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read(300)
        print("HTTP", resp.status, body[:180])
except Exception as e:
    print("HTTP_ERR", type(e).__name__, str(e)[:220])

# websockets quick
try:
    import asyncio, websockets
    ws_url = url
    if ws_url.startswith("https://"):
        ws_url = "wss://" + ws_url[len("https://"):]
    elif ws_url.startswith("http://"):
        ws_url = "ws://" + ws_url[len("http://"):]
    if "customerId" not in ws_url:
        sep = "&" if "?" in ws_url else "?"
        ws_url = f"{ws_url}{sep}customerId=726588"
    async def probe():
        async with websockets.connect(ws_url, open_timeout=15, close_timeout=5) as ws:
            await ws.send(json.dumps({"customerId": "726588"}))
            msg = await asyncio.wait_for(ws.recv(), timeout=15)
            raw = msg if isinstance(msg, str) else msg.decode("utf-8", "replace")
            print("WS_OK bytes", len(raw))
            try:
                d = json.loads(raw)
                prods = d.get("products") or (d.get("data") or {}).get("products") if isinstance(d.get("data"), dict) else d.get("data")
                if isinstance(prods, list):
                    print("WS_PRODUCTS", len(prods))
                    print("WS_NAME", d.get("primerNombre") or (d.get("data") or {}).get("primerNombre") if isinstance(d.get("data"), dict) else None)
                else:
                    print("WS_KEYS", list(d.keys())[:12] if isinstance(d, dict) else type(d))
            except Exception:
                print("WS_RAW_HEAD", raw[:120])
    asyncio.run(probe())
except Exception as e:
    print("WS_ERR", type(e).__name__, str(e)[:250])
'''


def main() -> int:
    pw = os.environ["SSH_DEPLOY_PASS"].strip()
    qa = paramiko.SSHClient()
    qa.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    qa.connect(
        "20.127.25.24",
        username="genesis",
        password=pw,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    sftp = qa.open_sftp()
    with sftp.open("/tmp/diag_core.py", "w") as fh:
        fh.write(REMOTE)
    sftp.close()

    def sudo(cmd: str, timeout: int = 120) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
        stdin, stdout, stderr = qa.exec_command(wrapped, get_pty=True, timeout=timeout)
        stdin.write(pw + "\n")
        stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", "replace")

    print("=== CORE PROBE ===")
    out = sudo("/opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python /tmp/diag_core.py")
    lines = [ln for ln in out.splitlines() if "password" not in ln.lower() and not ln.startswith("[sudo]")]
    print("\n".join(lines[-40:]).encode("ascii", "replace").decode("ascii"))

    print("=== ORCH CONTEXT ===")
    conv = f"diag-core-{int(time.time())}"
    cmd = (
        f"curl -sS -m 60 -X POST http://127.0.0.1:8447/orch/context "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"customer_id\":\"726588\",\"conversation_id\":\"{conv}\",\"allow_lab_fallback\":true}}' "
        f"-o /tmp/orch_ctx.json -w 'HTTP=%{{http_code}}\\n'; "
        "/opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python -c "
        "\"import json;d=json.load(open('/tmp/orch_ctx.json'));"
        "print('source',d.get('context_source'));"
        "print('portfolio',d.get('portfolio'));"
        "print('ws',d.get('core_websocket_url'));"
        "print('core_error',str(d.get('core_error'))[:350]);"
        "print('status',d.get('status'));"
        "print('name',d.get('display_name') or (d.get('customer_context') or {}).get('display_name'));"
        "print('keys',sorted([k for k in d.keys() if k!='client_response'])[:20])\""
    )
    out2 = sudo(cmd, timeout=90)
    lines2 = [ln for ln in out2.splitlines() if "password" not in ln.lower() and not ln.startswith("[sudo]")]
    print("\n".join(lines2[-25:]).encode("ascii", "replace").decode("ascii"))

    # also without lab fallback
    print("=== ORCH CONTEXT NO LAB ===")
    conv2 = f"diag-core-nl-{int(time.time())}"
    cmd2 = (
        f"curl -sS -m 60 -X POST http://127.0.0.1:8447/orch/context "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"customer_id\":\"726588\",\"conversation_id\":\"{conv2}\",\"allow_lab_fallback\":false}}' "
        f"-o /tmp/orch_ctx2.json -w 'HTTP=%{{http_code}}\\n'; "
        "python3 -c \"import json;d=json.load(open('/tmp/orch_ctx2.json')); print({k:d.get(k) for k in ('status','detail','context_source','error') if k in d or True}); print(str(d)[:400])\""
    )
    out3 = sudo(cmd2, timeout=90)
    lines3 = [ln for ln in out3.splitlines() if "password" not in ln.lower() and not ln.startswith("[sudo]")]
    print("\n".join(lines3[-20:]).encode("ascii", "replace").decode("ascii"))
    qa.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
