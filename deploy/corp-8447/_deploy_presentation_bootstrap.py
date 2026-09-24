#!/usr/bin/env python3
"""Deploy Presentation Product bootstrap files to QA :8447 (env SSH_DEPLOY_PASS)."""
from __future__ import annotations

import os
import pathlib
import shlex
import sys

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
APP = "/opt/genesis-cognitive-8447/Genesis_v2"
ENV_LINE = (
    "GENESIS_PRESENTATION_PRODUCT_URL_TEMPLATE="
    "https://apigateway-gen.qa.bsc.com.do/api/presentation/product/{customerId}"
)


def main() -> int:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        print("ERROR: define SSH_DEPLOY_PASS")
        return 1

    root = pathlib.Path(__file__).resolve().parents[2]
    files = [
        (
            root / "src/genesis_cognitive/context/presentation_product.py",
            f"{APP}/src/genesis_cognitive/context/presentation_product.py",
        ),
        (
            root / "src/genesis_cognitive/demo/contract_inspector_app.py",
            f"{APP}/src/genesis_cognitive/demo/contract_inspector_app.py",
        ),
        (
            root / "src/genesis_cognitive/demo/pruebas_ui/app.js",
            f"{APP}/src/genesis_cognitive/demo/pruebas_ui/app.js",
        ),
        (
            root / "src/genesis_cognitive/demo/pruebas_ui/index.html",
            f"{APP}/src/genesis_cognitive/demo/pruebas_ui/index.html",
        ),
        (
            root / "tests/unit/test_presentation_product.py",
            f"{APP}/tests/unit/test_presentation_product.py",
        ),
    ]

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting {USER}@{HOST}...")
    client.connect(HOST, username=USER, password=pw, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    for local, remote in files:
        if not local.is_file():
            print(f"MISSING {local}")
            return 1
        # ensure parent
        remote_dir = str(pathlib.PurePosixPath(remote).parent)
        try:
            sftp.stat(remote_dir)
        except OSError:
            stdin, stdout, stderr = client.exec_command(
                f"sudo -S mkdir -p {shlex.quote(remote_dir)} && sudo -S chown {USER}:{USER} {shlex.quote(remote_dir)}",
                get_pty=True,
            )
            stdin.write(pw + "\n")
            stdin.flush()
            stdout.channel.recv_exit_status()
        sftp.put(str(local), remote)
        print(f"PUT {local.name} -> {remote}")
    sftp.close()

    def sudo(cmd: str) -> tuple[int, str]:
        # Evitar get_pty para no ecoar la contraseña en logs.
        wrapped = f"echo {shlex.quote(pw)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        stdin, stdout, stderr = client.exec_command(wrapped, timeout=180)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        text = (out + err).strip()
        if text:
            # Nunca imprimir la contraseña si filtró
            text = text.replace(pw, "***")
            print(text[-4000:])
        return code, text

    # upsert env
    env_path = f"{APP}/.env"
    upsert = f"""
set -e
ENV={shlex.quote(env_path)}
KEY=GENESIS_PRESENTATION_PRODUCT_URL_TEMPLATE
VAL='https://apigateway-gen.qa.bsc.com.do/api/presentation/product/{{customerId}}'
if grep -q "^${{KEY}}=" "$ENV" 2>/dev/null; then
  sed -i "s|^${{KEY}}=.*|${{KEY}}=${{VAL}}|" "$ENV"
else
  printf '\\n%s=%s\\n' "$KEY" "$VAL" >> "$ENV"
fi
grep -q '^GENESIS_PRESENTATION_ALLOW_INSECURE_TLS=' "$ENV" || echo 'GENESIS_PRESENTATION_ALLOW_INSECURE_TLS=1' >> "$ENV"
grep -E '^GENESIS_PRESENTATION_' "$ENV" || true
systemctl restart genesis-cognitive-8447
sleep 3
systemctl is-active genesis-cognitive-8447
curl -sS -m 8 http://127.0.0.1:8447/health || true
"""
    code, _ = sudo(upsert)
    if code != 0:
        print("ENV/restart failed", code)
        return code

    # validate from VM
    validate = r"""
set -e
python3 - <<'PY'
import json, urllib.request, uuid, re
BASE='http://127.0.0.1:8447'
cid=str(uuid.uuid4())
body=json.dumps({'customer_id':'726588','conversation_id':cid,'allow_lab_fallback':False}).encode()
req=urllib.request.Request(BASE+'/orch/context', data=body, headers={'Content-Type':'application/json'}, method='POST')
try:
    with urllib.request.urlopen(req, timeout=90) as r:
        d=json.loads(r.read().decode())
except Exception as e:
    if hasattr(e,'read'):
        print('CTX_FAIL', e.code if hasattr(e,'code') else '', e.read()[:400].decode('utf-8','replace'))
    else:
        print('CTX_FAIL', e)
    raise SystemExit(1)
print('SOURCE', d.get('context_source'))
print('STATUS', d.get('status'))
print('PRODUCTS', d.get('products_count'))
print('ACTIVE', d.get('active_count'))
print('HAS_PRES_URL', bool(d.get('presentation_product_url')))
# turn question
tbody=json.dumps({
  'question':'Que productos tengo?',
  'customer_id':'726588',
  'conversation_id': d.get('conversation_id') or cid,
  'context_info': False,
}).encode()
req2=urllib.request.Request(BASE+'/turn', data=tbody, headers={'Content-Type':'application/json'}, method='POST')
with urllib.request.urlopen(req2, timeout=120) as r2:
    t=json.loads(r2.read().decode())
app=t.get('app_channel') or {}
reply=(t.get('reply') or app.get('client_response') or '')[:200]
reply=re.sub(r'\b\d{4,}\b','####', reply)
print('REPLY', reply)
print('INTENT', app.get('intent_id'))
PY
# also probe presentation DNS from VM
getent hosts apigateway-gen.qa.bsc.com.do || true
curl -sk -m 15 -o /tmp/pres.json -w 'PRES_HTTP=%{http_code}\n' \
  'https://apigateway-gen.qa.bsc.com.do/api/presentation/product/726588' || true
python3 -c "import json;d=json.load(open('/tmp/pres.json')); print('PRES_KEYS', list(d)[:8] if isinstance(d,dict) else type(d)); print('HAS_DATA', 'data' in d if isinstance(d,dict) else False)" 2>/dev/null || head -c 200 /tmp/pres.json; echo
"""
    sudo(validate)
    client.close()
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
