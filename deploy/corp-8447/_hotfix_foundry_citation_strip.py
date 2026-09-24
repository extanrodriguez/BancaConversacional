"""Hotfix QA 8447 — limpiar dumps de citas Foundry en respuestas KB.

No altera routing Azure tool_choice ni chitchat. Solo sanitiza salida.
"""
from __future__ import annotations

import os
import pathlib
import shlex
import time

import paramiko

LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
SRC = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional")
REMOTE_LAB = "/opt/genesis-cognitive-8447/lab8446_runtime"

# (local_path, remote_path)
FILES = [
    (LAB / "lab8446" / "reply_format.py", f"{REMOTE_LAB}/lab8446/reply_format.py"),
    (
        SRC / "src" / "genesis_cognitive" / "rag" / "foundry_kb_agent.py",
        f"{REMOTE_LAB}/sibling_src/genesis_cognitive/rag/foundry_kb_agent.py",
    ),
    (
        SRC / "src" / "genesis_cognitive" / "context" / "response_formatting.py",
        f"{REMOTE_LAB}/sibling_src/genesis_cognitive/context/response_formatting.py",
    ),
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
    for local, remote in FILES:
        if not local.is_file():
            print(f"MISSING {local}")
            return 1
        tmp = f"/tmp/hotfix_cite_{local.name}_{ts}"
        print(f"PUT {local.name} -> {tmp}")
        sftp.put(str(local), tmp)
        remote_tmp.append((tmp, remote))
    sftp.close()

    def run_sudo(cmd: str) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _stdin, stdout, stderr = client.exec_command(wrapped, timeout=180)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            print(out[-10000:])
        return code, out

    copies = " && ".join(
        f"cp -f {shlex.quote(src)} {shlex.quote(dst)} && chown genesis:genesis {shlex.quote(dst)}"
        for src, dst in remote_tmp
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(src)}" for src, _ in remote_tmp)
    # Limpiar cache Foundry contaminado si existe
    cache_rm = (
        f"rm -rf {REMOTE_LAB}/data/cache/foundry_kb 2>/dev/null || true; "
        f"rm -rf {REMOTE_LAB}/sibling_src/../data/cache/foundry_kb 2>/dev/null || true; "
        "find /opt/genesis-cognitive-8447 -type d -name foundry_kb 2>/dev/null | head -5"
    )
    code, _ = run_sudo(
        f"test -d {REMOTE_LAB}/lab8446 || {{ echo MISSING_LAB; exit 2; }}; "
        f"{copies} && "
        f"{cache_rm}; "
        "systemctl restart genesis-cognitive-8447.service; sleep 6; "
        "systemctl is-active genesis-cognitive-8447.service; "
        "curl -sf -m 10 http://127.0.0.1:8447/health; echo; "
        f"{cleanup}"
    )
    if code != 0:
        client.close()
        return code

    code2, out2 = run_sudo(
        r"""python3 - <<'PY'
import json, urllib.request, re
req = urllib.request.Request(
    'http://127.0.0.1:8447/turn',
    data=json.dumps({
        'conversation_id': 'smoke-fecha-corte-cite',
        'question': 'Fecha de corte',
        'customer_id': '726588',
        'debug': True,
    }).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=120) as r:
    body = json.loads(r.read().decode())
reply = body.get('reply') or body.get('message') or ''
print('REPLY_LEN', len(reply))
print('REPLY_PREFIX', reply[:400].replace('\n', ' | '))
print('HAS_PIPE_DUMP', bool(re.search(r'\|\s*\d{2,}\s*\|', reply)))
print('HAS_SOURCE_MARK', 'source' in reply.lower() and ('†' in reply or '‡' in reply or ':2' in reply))
print('HAS_CORTE', 'corte' in reply.lower())
print('HAS_THOUSANDS', bool(re.search(r'\b9\d{2}\b.*\b1000\b', reply)))
dbg = body.get('debug') or {}
print('DEBUG_MODE', dbg.get('mode'))
PY"""
    )
    client.close()
    return 0 if code2 == 0 else code2


if __name__ == "__main__":
    raise SystemExit(main())
