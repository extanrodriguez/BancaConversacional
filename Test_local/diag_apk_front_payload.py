"""Profund APK /chat/front desde la VM (localhost) y detalle del handler."""
from __future__ import annotations

import json
import os
import shlex
import sys

import paramiko


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=30, look_for_keys=False, allow_agent=False)

    def run(cmd: str, *, sudo: bool = False) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

    print("=== handler snippet ===")
    print(run("sed -n '450,520p' /opt/genesis-rag/app/main.py"))
    print("=== env keys (masked) ===")
    print(run("grep -E 'API_KEY|X_API|FRONT|CHAT' /opt/genesis-rag/.env /opt/genesis-rag/app/.env 2>/dev/null | sed 's/=.*/=***/' || true", sudo=True))
    print("=== find api key var ===")
    print(run("grep -n 'check_key\\|API_KEY\\|x-api-key' /opt/genesis-rag/app/main.py | head -40"))
    print("=== process on 8000 ===")
    print(run("ps -fp 241896 2>/dev/null; tr '\\0' ' ' < /proc/241896/cmdline 2>/dev/null; echo; ls -la /proc/241896/cwd 2>/dev/null", sudo=True))
    print("=== firewall/nft ===")
    print(run("sudo iptables -L INPUT -n 2>/dev/null | head -30; sudo ufw status 2>/dev/null | head -20", sudo=True))

    # Extract real key carefully on server and test without printing full key
    script = r'''
python3 - <<'PY'
import json,re,os,urllib.request,uuid,time
from pathlib import Path
env_paths=[Path('/opt/genesis-rag/.env'),Path('/opt/genesis-rag/app/.env')]
key=None
for p in env_paths:
    if p.is_file():
        for line in p.read_text(errors='replace').splitlines():
            if 'API_KEY' in line.upper() and '=' in line and not line.strip().startswith('#'):
                key=line.split('=',1)[1].strip().strip('"').strip("'")
                print('KEY_SOURCE', p, 'LEN', len(key), 'PREFIX', key[:4]+'...')
                break
    if key: break
if not key:
    # try main.py default
    text=Path('/opt/genesis-rag/app/main.py').read_text(errors='replace')
    m=re.search(r'API_KEY\s*=\s*["\']([^"\']+)["\']', text)
    if m:
        key=m.group(1)
        print('KEY_SOURCE main.py LEN', len(key), 'PREFIX', key[:4]+'...')
if not key:
    print('NO_KEY'); raise SystemExit(0)

def post(payload, use_q=True):
    url='http://127.0.0.1:8000/chat/front'
    if use_q:
        url += f'?x-api-key={key}'
    data=json.dumps(payload).encode()
    req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json','x-api-key':key},method='POST')
    t0=time.time()
    try:
        with urllib.request.urlopen(req,timeout=40) as r:
            body=r.read().decode()
            print('OK', r.status, f'{time.time()-t0:.2f}s', body[:300])
    except Exception as e:
        print('ERR', type(e).__name__, e, f'{time.time()-t0:.2f}s')
        if hasattr(e,'read'):
            try: print(e.read().decode()[:400])
            except Exception: pass

cid=f'apk_{uuid.uuid4().hex[:8]}'
# APK-like payloads
for name,payload in [
 ('question+client', {'question':'hola','client_id':'TEST-QA-001','conversation_id':cid}),
 ('message+client', {'message':'hola','client_id':'TEST-QA-001','conversation_id':cid}),
 ('question only', {'question':'dame el balance de mis cuentas','client_id':'USUARIO1','conversation_id':cid+'-2'}),
]:
    print('---', name)
    post(payload)
PY
'''
    print("=== local APK-like calls ===")
    print(run(script, sudo=True))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
