"""Hotfix QA 8447 — saludos/chitchat sin listar productos."""
from __future__ import annotations

import os
import pathlib
import shlex
import time

import paramiko

LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
REMOTE_LAB = "/opt/genesis-cognitive-8447/lab8446_runtime"
FILES = [
    "lab8446/semantic_intent.py",
    "lab8446/agent.py",
    "lab8446/tools.py",
]


def _password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = pathlib.Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
    if not pw:
        raise SystemExit("ERROR: SSH_DEPLOY_PASS")
    return pw


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host}...")
    client.connect(
        host, username=user, password=password, timeout=40,
        look_for_keys=False, allow_agent=False,
    )
    sftp = client.open_sftp()
    ts = int(time.time())
    remote_tmp: list[tuple[str, str]] = []
    for rel in FILES:
        local = LAB / rel
        if not local.is_file():
            print(f"MISSING {local}")
            return 1
        tmp = f"/tmp/hotfix_greet_{pathlib.Path(rel).name}_{ts}"
        print(f"PUT {rel}")
        sftp.put(str(local), tmp)
        remote_tmp.append((tmp, f"{REMOTE_LAB}/{rel}"))
    sftp.close()

    def run_sudo(cmd: str) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _stdin, stdout, stderr = client.exec_command(wrapped, timeout=180)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            print(out[-6000:])
        return code, out

    copies = " && ".join(
        f"cp -f {shlex.quote(s)} {shlex.quote(d)} && chown genesis:genesis {shlex.quote(d)}"
        for s, d in remote_tmp
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(s)}" for s, _ in remote_tmp)
    code, _ = run_sudo(
        f"test -d {REMOTE_LAB}/lab8446 || exit 2; {copies} && "
        "systemctl restart genesis-cognitive-8447.service; sleep 5; "
        "systemctl is-active genesis-cognitive-8447.service; "
        "curl -sf -m 8 http://127.0.0.1:8447/health; echo; "
        f"{cleanup}"
    )
    if code != 0:
        client.close()
        return code

    code2, _ = run_sudo(
        r"""python3 - <<'PY'
import json, urllib.request

def turn(q):
    req = urllib.request.Request(
        'http://127.0.0.1:8447/turn',
        data=json.dumps({
            'conversation_id': 'smoke-greet',
            'question': q,
            'customer_id': '726588',
            'debug': True,
        }).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

for q in ['hola', 'buenos dias', 'gracias']:
    b = turn(q)
    reply = (b.get('reply') or '')
    dbg = b.get('debug') or {}
    print('Q', q)
    print(' MODE', dbg.get('mode'), 'intent', (dbg.get('intent') or {}).get('domain'))
    print(' REPLY', reply[:120].encode('ascii','replace').decode('ascii'))
    print(' HAS_PRODUCT_LIST', 'Encontre' in reply or 'Encontré' in reply or 'producto(s)' in reply)
PY"""
    )
    client.close()
    return code2


if __name__ == "__main__":
    raise SystemExit(main())
