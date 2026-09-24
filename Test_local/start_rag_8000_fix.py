"""Arranca genesis-rag en :8000 de forma robusta."""
from __future__ import annotations

import os
import shlex
import time

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

    def run(cmd: str, *, sudo: bool = False) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

    # Write a start script on the VM
    script = r'''#!/bin/bash
set -euo pipefail
cd /opt/genesis-rag
set -a
. /opt/genesis-rag/.env
set +a
pkill -f 'uvicorn app.main:app --host 0.0.0.0 --port 8000' || true
sleep 1
nohup /opt/genesis-rag/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  > /tmp/genesis-rag-8000.log 2>&1 &
echo $! > /tmp/genesis-rag-8000.pid
sleep 2
ss -tlnp | grep :8000 || (echo FAIL; tail -n 50 /tmp/genesis-rag-8000.log; exit 1)
curl -sS -m 5 http://127.0.0.1:8000/health
echo
'''
    # upload via echo/heredoc carefully
    put = "cat > /tmp/start_rag_8000.sh <<'EOF'\n" + script + "EOF\nchmod +x /tmp/start_rag_8000.sh"
    print(run(put, sudo=True))
    print(run("bash /tmp/start_rag_8000.sh", sudo=True))
    print("=== log ===")
    print(run("tail -n 40 /tmp/genesis-rag-8000.log || true"))
    print("=== proxy file ===")
    print(run("head -n 90 /opt/genesis-rag/app/cognitive_front_proxy.py | sed -n '70,100p'"))
    print("=== main handler ===")
    print(run("sed -n '469,495p' /opt/genesis-rag/app/main.py"))
    print("=== smoke ===")
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
  print('OK', list(payload), body.get('status'), str(body.get('reply') or '')[:140])
PY
'''
    print(run(smoke, sudo=True))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
