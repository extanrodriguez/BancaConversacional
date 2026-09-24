"""Test /chat/front local en VM con GENESIS_API_KEY real (sin imprimirla)."""
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

    cmd = r'''
set -a
. /opt/genesis-rag/.env
set +a
python3 - <<'PY'
import json, os, time, uuid, urllib.request, urllib.error
key = os.environ.get("GENESIS_API_KEY", "")
print("key_len", len(key))

def call(payload):
    url = f"http://127.0.0.1:8000/chat/front?x-api-key={key}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = json.loads(r.read().decode())
            print("OK", round(time.time()-t0,2), "s", "status", body.get("status"), "reply", str(body.get("reply") or "")[:160], "opts", len(body.get("options") or []))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, round(time.time()-t0,2), e.read().decode()[:300])
    except Exception as e:
        print("ERR", type(e).__name__, e, round(time.time()-t0,2))

cid = "apkdiag_" + uuid.uuid4().hex[:8]
call({"question": "hola", "client_id": "TEST-QA-001", "conversation_id": cid})
call({"question": "dame un balance de mis cuentas", "client_id": "TEST-QA-001", "conversation_id": cid})
call({"message": "hola", "client_id": "TEST-QA-001", "conversation_id": cid + "b"})  # si APK manda message
PY
'''
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
    stdin.write(password + "\n")
    stdin.flush()
    print((stdout.read() + stderr.read()).decode("utf-8", errors="replace"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
