"""Actualiza proxy APK /chat/front en la VM (solo genesis-rag :8000 → 8447)."""
from __future__ import annotations

import os
import shlex
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
PROXY = ROOT / "deploy" / "rag-proxy" / "cognitive_front_proxy.py"
PATCH = ROOT / "deploy" / "rag-proxy" / "patch_rag_front.py"


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    if not password:
        print("ERROR: SSH_DEPLOY_PASS")
        return 1
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    sftp.put(str(PROXY), "/tmp/cognitive_front_proxy.py")
    sftp.put(str(PATCH), "/tmp/patch_rag_front.py")
    sftp.close()

    def run(cmd: str, *, sudo: bool = False) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

    print(run("python3 /tmp/patch_rag_front.py", sudo=True))
    # Reiniciar proceso uvicorn en :8000
    print(run(
        "pkill -f 'uvicorn app.main:app --host 0.0.0.0 --port 8000' || true; "
        "sleep 1; "
        "cd /opt/genesis-rag && nohup .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 "
        "> /tmp/genesis-rag-8000.log 2>&1 & sleep 2; "
        "ss -tlnp | grep :8000; "
        "curl -sS -m 5 http://127.0.0.1:8000/health",
        sudo=True,
    ))

    # Smoke con key
    smoke = r'''
set -a; . /opt/genesis-rag/.env; set +a
python3 - <<'PY'
import json,os,urllib.request,uuid
key=os.environ['GENESIS_API_KEY']
cid='fix_'+uuid.uuid4().hex[:8]
for payload in [
 {'question':'hola','client_id':'TEST-QA-001','conversation_id':cid},
 {'message':'dame un balance de mis cuentas','client_id':'TEST-QA-001','conversation_id':cid},
]:
  url=f'http://127.0.0.1:8000/chat/front?x-api-key={key}'
  req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
  with urllib.request.urlopen(req,timeout=30) as r:
    body=json.loads(r.read().decode())
  print('OK', payload, '->', body.get('status'), str(body.get('reply') or '')[:120])
PY
'''
    print(run(smoke, sudo=True))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
