"""Hotfix 8447 — KB: no aclarar «depósito a plazo es una cuenta?» + query completa."""
from __future__ import annotations

import os
import pathlib
import shlex
import time
from datetime import datetime, timezone

import paramiko

ROOT = pathlib.Path(__file__).resolve().parents[2]
LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
REMOTE_PARENT = "/opt/genesis-cognitive-8447"
REMOTE_LAB = f"{REMOTE_PARENT}/lab8446_runtime"
SERVICE = "genesis-cognitive-8447.service"

FILES = [
    (ROOT / "src/genesis_cognitive/rag/foundry_kb_agent.py", "sibling"),
    (LAB / "lab8446/agent.py", "lab"),
    (LAB / "lab8446/tools.py", "lab"),
]

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
TAG = f"kb_cd_vs_cuenta_{STAMP}"


def _password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        raise SystemExit("ERROR: SSH_DEPLOY_PASS")
    return pw


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    for path, _ in FILES:
        if not path.is_file():
            print("MISSING", path)
            return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=40, look_for_keys=False, allow_agent=False)

    def run(cmd: str, timeout: int = 300) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _, stdout, stderr = client.exec_command(wrapped, timeout=timeout)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            print(out[-10000:])
        return code, out

    bak = f"{REMOTE_PARENT}/backups/{TAG}"
    run(
        f"mkdir -p {bak}/lab8446 {bak}/sibling_src/genesis_cognitive/rag && "
        f"cp -a {REMOTE_LAB}/lab8446/agent.py {bak}/lab8446/ 2>/dev/null; "
        f"cp -a {REMOTE_LAB}/lab8446/tools.py {bak}/lab8446/ 2>/dev/null; "
        f"cp -a {REMOTE_LAB}/sibling_src/genesis_cognitive/rag/foundry_kb_agent.py "
        f"{bak}/sibling_src/genesis_cognitive/rag/ 2>/dev/null; "
        f"tar -czf {bak}.tar.gz -C {REMOTE_PARENT}/backups {TAG} && echo BACKUP_OK"
    )

    sftp = client.open_sftp()
    ts = int(time.time())
    copies = []
    tmps = []
    for path, kind in FILES:
        tmp = f"/tmp/hotfix_kbcd_{path.name}_{ts}"
        sftp.put(str(path), tmp)
        tmps.append(tmp)
        if kind == "lab":
            dst = f"{REMOTE_LAB}/lab8446/{path.name}"
        else:
            dst = f"{REMOTE_LAB}/sibling_src/genesis_cognitive/rag/{path.name}"
            leg = f"{REMOTE_PARENT}/Genesis_v2/src/genesis_cognitive/rag/{path.name}"
            copies.append(
                f"mkdir -p $(dirname {leg}); cp -f {tmp} {leg}; chown genesis:genesis {leg}"
            )
        copies.append(f"cp -f {tmp} {dst}; chown genesis:genesis {dst}; echo COPIED {dst}")
    sftp.close()

    cleanup = " ; ".join(f"rm -f {t}" for t in tmps)
    code, out = run(
        " && ".join(copies)
        + f" && grep -n 'es una cuenta' {REMOTE_LAB}/sibling_src/genesis_cognitive/rag/foundry_kb_agent.py | head -3; "
        f"grep -n 'Anclar SIEMPRE' {REMOTE_LAB}/lab8446/agent.py | head -2; "
        f"systemctl restart {SERVICE}; sleep 6; systemctl is-active {SERVICE}; "
        f"curl -sf -m 10 http://127.0.0.1:8447/health; echo; {cleanup}; echo DEPLOY_OK"
    )
    if code != 0 or "DEPLOY_OK" not in out:
        client.close()
        return 4

    code2, out2 = run(
        r"""python3 - <<'PY'
import json, urllib.request, re
req = urllib.request.Request(
    'http://127.0.0.1:8447/turn',
    data=json.dumps({
        'conversation_id': 'smoke-cd-es-cuenta',
        'question': 'un deposito a plazo es una cuenta?',
        'customer_id': '726588',
        'debug': True,
    }).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=90) as r:
    b = json.loads(r.read().decode())
reply = b.get('reply') or ''
d = b.get('debug') or {}
print('MODE', d.get('mode'))
print('TOOLS', d.get('azure_chose_tools'))
print('ARGS', (d.get('tool_calls') or [{}])[0].get('args'))
print('REPLY', reply[:700].encode('ascii','replace').decode('ascii'))
clarify = 'garant' in reply.lower() and 'te refieres' in reply.lower()
answers = bool(re.search(r'no\b|inversi|certificado|no es una cuenta|producto', reply, re.I))
print('CHECKS', {'not_clarify': not clarify, 'answers': answers, 'kb': d.get('mode') in ('foundry_kb_agent','azure_openai_tools')})
print('SMOKE_OK' if (not clarify and answers) else 'SMOKE_FAIL')
PY"""
    )
    client.close()
    if code2 != 0 or "SMOKE_OK" not in out2:
        return 6
    print(f"OK {TAG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
