"""Hotfix QA 8447 — fix Foundry KB descartado + expand query off-topic."""
from __future__ import annotations

import os
import pathlib
import shlex
import time

import paramiko

LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
REMOTE_LAB = "/opt/genesis-cognitive-8447/lab8446_runtime"
FILES = ["lab8446/kb_search.py"]


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
        tmp = f"/tmp/hotfix_kb_fix_{pathlib.Path(rel).name}_{ts}"
        print(f"PUT {rel} -> {tmp}")
        sftp.put(str(local), tmp)
        remote_tmp.append((tmp, f"{REMOTE_LAB}/{rel}"))
    sftp.close()

    def run_sudo(cmd: str) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _stdin, stdout, stderr = client.exec_command(wrapped, timeout=180)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            print(out[-8000:])
        return code, out

    copies = " && ".join(
        f"cp -f {shlex.quote(src)} {shlex.quote(dst)} && chown genesis:genesis {shlex.quote(dst)}"
        for src, dst in remote_tmp
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(src)}" for src, _ in remote_tmp)
    code, _ = run_sudo(
        f"test -d {REMOTE_LAB}/lab8446 || {{ echo MISSING_LAB; exit 2; }}; "
        f"{copies} && "
        "systemctl restart genesis-cognitive-8447.service; sleep 6; "
        "systemctl is-active genesis-cognitive-8447.service; "
        "curl -sf -m 10 http://127.0.0.1:8447/health; echo; "
        f"{cleanup}"
    )
    if code != 0:
        client.close()
        return code

    # Smoke turn
    code2, out2 = run_sudo(
        r"""python3 - <<'PY'
import json, urllib.request
req = urllib.request.Request(
    'http://127.0.0.1:8447/turn',
    data=json.dumps({
        'conversation_id': 'smoke-kb-visa',
        'question': 'hablame de la visa platinum',
        'customer_id': '726588',
        'debug': True,
    }).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=90) as r:
    body = json.loads(r.read().decode())
reply = body.get('reply') or ''
print('REPLY_PREFIX', reply[:350].replace('\n',' | '))
print('HAS_PLATINUM', 'platinum' in reply.lower())
print('HEDGE_FAIL', 'no tengo información específica' in reply.lower())
dbg = body.get('debug') or {}
print('DEBUG_MODE', dbg.get('mode'))
print('TOOL', (dbg.get('tool_calls') or [{}])[0] if dbg.get('tool_calls') else None)
PY"""
    )
    client.close()
    print("OK — hotfix KB Foundry aplicado" if code2 == 0 else f"SMOKE_FAIL {code2}")
    return code2


if __name__ == "__main__":
    raise SystemExit(main())
