"""Reinicia genesis-rag :8000 y valida /chat/front."""
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

    print("=== status before ===")
    print(run("ss -tlnp | grep :8000 || echo DOWN"))

    # Start as genesis user (same as previous process)
    start = (
        "pkill -f 'uvicorn app.main:app --host 0.0.0.0 --port 8000' || true; "
        "sleep 1; "
        "cd /opt/genesis-rag && "
        "sudo -u genesis env HOME=/home/genesis bash -lc '"
        "set -a; . /opt/genesis-rag/.env; set +a; "
        "cd /opt/genesis-rag; "
        "nohup .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 "
        "> /tmp/genesis-rag-8000.log 2>&1 & echo STARTED:$!"
        "'"
    )
    print(run(start, sudo=True))
    time.sleep(3)
    print("=== status after ===")
    print(run("ss -tlnp | grep :8000 || echo DOWN; tail -n 30 /tmp/genesis-rag-8000.log 2>/dev/null || true"))
    print("=== health ===")
    print(run("curl -sS -m 5 http://127.0.0.1:8000/health || true"))
    print("=== smoke ===")
    smoke = r'''
set -a; . /opt/genesis-rag/.env; set +a
python3 - <<'PY'
import json,os,urllib.request,uuid
key=os.environ.get('GENESIS_API_KEY','')
print('key_len', len(key))
cid='fix_'+uuid.uuid4().hex[:8]
for payload in [
 {'question':'hola','client_id':'TEST-QA-001','conversation_id':cid},
 {'message':'dame un balance de mis cuentas','client_id':'TEST-QA-001','conversation_id':cid},
]:
  url=f'http://127.0.0.1:8000/chat/front?x-api-key={key}'
  req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
  with urllib.request.urlopen(req,timeout=30) as r:
    body=json.loads(r.read().decode())
  print('OK', list(payload.keys()), body.get('status'), str(body.get('reply') or '')[:140])
PY
'''
    print(run(smoke, sudo=True))
    print("=== handler uses message alias? ===")
    print(run("grep -n 'message\\|payload.get' /opt/genesis-rag/app/main.py | sed -n '470,500p'"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
