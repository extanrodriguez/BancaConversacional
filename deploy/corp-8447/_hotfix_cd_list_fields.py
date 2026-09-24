"""Hotfix 8447 — CD en listados con todos los campos de negocio (Azure sigue interpretando)."""
from __future__ import annotations

import os
import pathlib
import shlex
import time
from datetime import datetime, timezone

import paramiko

LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
ROOT = pathlib.Path(__file__).resolve().parents[2]
REMOTE = "/opt/genesis-cognitive-8447/lab8446_runtime"
FILES = ["lab8446/tools.py", "lab8446/agent.py", "lab8446/models.py"]
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
TAG = f"cd_list_fields_{STAMP}"


def _password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        raise SystemExit("ERROR: SSH_DEPLOY_PASS")
    return pw


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
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

    bak = f"/opt/genesis-cognitive-8447/backups/{TAG}"
    bak_cmds = [f"mkdir -p {bak}/lab8446"]
    for rel in FILES:
        bak_cmds.append(f"cp -a {REMOTE}/{rel} {bak}/{rel}")
    bak_cmds.append(
        f"tar -czf {bak}.tar.gz -C /opt/genesis-cognitive-8447/backups {TAG} && echo BACKUP_OK"
    )
    code_b, out_b = run(" && ".join(bak_cmds))
    if code_b != 0 or "BACKUP_OK" not in out_b:
        client.close()
        return 3

    (ROOT / "backups" / TAG).mkdir(parents=True, exist_ok=True)
    (ROOT / "backups" / TAG / "README.txt").write_text(
        f"{TAG}\n{bak}.tar.gz\n" + "\n".join(FILES), encoding="utf-8"
    )

    sftp = client.open_sftp()
    ts = int(time.time())
    tmps: list[tuple[str, str]] = []
    for rel in FILES:
        tmp = f"/tmp/hotfix_cdlf_{pathlib.Path(rel).name}_{ts}"
        sftp.put(str(LAB / rel), tmp)
        tmps.append((tmp, f"{REMOTE}/{rel}"))
    sftp.close()

    copies = " && ".join(
        f"cp -f {shlex.quote(s)} {shlex.quote(d)} && chown genesis:genesis {shlex.quote(d)}"
        for s, d in tmps
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(s)}" for s, _ in tmps)
    code, out = run(
        f"{copies} && systemctl restart genesis-cognitive-8447.service; sleep 6; "
        "systemctl is-active genesis-cognitive-8447.service; "
        "curl -sf -m 10 http://127.0.0.1:8447/health; echo; "
        f"{cleanup}; echo DEPLOY_OK"
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
        'conversation_id': 'smoke-cd-list-v2',
        'question': 'lista mis productos',
        'customer_id': '726588',
        'debug': True,
    }).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=90) as r:
    b = json.loads(r.read().decode())
reply = b.get('reply') or ''
# último bloque Certificado
blocks = list(re.finditer(r'\*\*\d+\.\s*Certificado[^\n]*.*?(?=\n\*\*\d+\.|\n\d+\.|\nSi necesitas|$)', reply, re.S|re.I))
if not blocks:
    blocks = list(re.finditer(r'Certificado de Dep[oó]sito.*?(?=\n\n\d+\.|\nSi necesitas|$)', reply, re.S|re.I))
block = blocks[-1].group(0) if blocks else ''
print('CD_BLOCK', block[:800].encode('ascii','replace').decode('ascii'))
has_rate = bool(re.search(r'tasa|8\.15|interest_rate', block, re.I))
has_int = bool(re.search(r'intereses', block, re.I))
has_cap = bool(re.search(r'capital|saldo|disponible|150,?000|180,?755', block, re.I))
has_mat = bool(re.search(r'vencim|2026-09-19|19/09', block, re.I))
print('CHECKS', {'rate': has_rate, 'intereses': has_int, 'capital': has_cap, 'venc': has_mat})
print('MODE', (b.get('debug') or {}).get('mode'))
print('CD_LIST_OK' if (has_rate and has_int and (has_cap or has_mat)) else 'CD_LIST_FAIL')
PY"""
    )
    client.close()
    if code2 != 0 or "CD_LIST_OK" not in out2:
        return 6
    print(f"OK {TAG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
