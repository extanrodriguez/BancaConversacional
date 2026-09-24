"""Deploy: wrapper campos de negocio + product_context restaurado (sin bypass intent)."""
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
FILES = [
    "lab8446/business_fields.py",
    "lab8446/models.py",
    "lab8446/portfolio_loader.py",
    "lab8446/product_context_service.py",
    "lab8446/tools.py",
    "lab8446/agent.py",
]
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
TAG = f"business_wrapper_{STAMP}"


def _password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        raise SystemExit("ERROR: SSH_DEPLOY_PASS")
    return pw


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    for rel in FILES:
        if not (LAB / rel).is_file():
            print("MISSING", LAB / rel)
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
            print(out[-12000:])
        return code, out

    bak = f"/opt/genesis-cognitive-8447/backups/{TAG}"
    bak_cmds = [f"mkdir -p {bak}/lab8446"]
    for rel in FILES:
        bak_cmds.append(
            f"if [ -f {REMOTE}/{rel} ]; then cp -a {REMOTE}/{rel} {bak}/{rel}; fi"
        )
    bak_cmds.append(
        f"tar -czf {bak}.tar.gz -C /opt/genesis-cognitive-8447/backups {TAG} && echo BACKUP_OK"
    )
    code_b, out_b = run(" && ".join(bak_cmds))
    if code_b != 0 or "BACKUP_OK" not in out_b:
        client.close()
        return 3

    (ROOT / "backups" / TAG).mkdir(parents=True, exist_ok=True)
    (ROOT / "backups" / TAG / "README.txt").write_text(
        f"{TAG}\n" + "\n".join(FILES), encoding="utf-8"
    )

    sftp = client.open_sftp()
    ts = int(time.time())
    tmps: list[tuple[str, str]] = []
    for rel in FILES:
        tmp = f"/tmp/hotfix_bw_{pathlib.Path(rel).name}_{ts}"
        sftp.put(str(LAB / rel), tmp)
        tmps.append((tmp, f"{REMOTE}/{rel}"))
    sftp.close()

    copies = " && ".join(
        f"mkdir -p $(dirname {shlex.quote(d)}) && cp -f {shlex.quote(s)} {shlex.quote(d)} "
        f"&& chown genesis:genesis {shlex.quote(d)}"
        for s, d in tmps
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(s)}" for s, _ in tmps)
    # Invalidar portfolio cache del cliente QA para forzar re-wrap
    purge = (
        "python3 - <<'PY'\n"
        "import os\n"
        "try:\n"
        "  import redis\n"
        "  # best-effort: key customer:726588:portfolio\n"
        "  print('PURGE_SKIP_USE_APP')\n"
        "except Exception as e:\n"
        "  print('purge', e)\n"
        "PY"
    )
    code, out = run(
        f"{copies} && grep -n 'DiaDeCorte' {REMOTE}/lab8446/business_fields.py | head -2; "
        f"grep -n 'campos_negocio' {REMOTE}/lab8446/models.py | head -2; "
        f"systemctl restart genesis-cognitive-8447.service; sleep 6; "
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

def turn(q, cid):
    req = urllib.request.Request(
        'http://127.0.0.1:8447/turn',
        data=json.dumps({
            'conversation_id': cid,
            'question': q,
            'customer_id': '726588',
            'debug': True,
        }).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())

b = turn('Dime el saldo de mi cuenta de ahorros.', 'smoke-ahorros-intent')
reply = b.get('reply') or ''
dbg = b.get('debug') or {}
tr = b.get('tool_result') or {}
print('MODE', dbg.get('mode'))
print('TOOLS', dbg.get('azure_chose_tools'))
print('ARGS', (dbg.get('tool_calls') or [{}])[0].get('args'))
print('REPLY', reply[:500].encode('ascii','replace').decode('ascii'))
raw_dump = 'Encontré' in reply or 'ACCOUNT ' in reply or 'product_ref' in reply.lower()
mentions_corriente = bool(re.search(r'corriente|31,?200|28,?500', reply, re.I))
mentions_ahorros = bool(re.search(r'ahorros|50,?000|581', reply, re.I))
print('CHECKS', {
    'azure_mode': dbg.get('mode') == 'azure_openai_tools',
    'not_raw_dump': not raw_dump,
    'mentions_ahorros': mentions_ahorros,
    'no_corriente': not mentions_corriente,
})
# tool products sample keys
prods = tr.get('products') or []
if not prods:
    # debug may nest differently
    for c in dbg.get('tool_calls') or []:
        pass
print('TOOL_PRODS', len(prods))
if prods:
    print('KEYS_SAMPLE', sorted(prods[0].keys())[:20])
ok = (dbg.get('mode') == 'azure_openai_tools' and not raw_dump and mentions_ahorros and not mentions_corriente)
print('SMOKE_OK' if ok else 'SMOKE_FAIL')
PY"""
    )
    client.close()
    if code2 != 0 or "SMOKE_OK" not in out2:
        print("FAIL smoke")
        return 6
    print(f"OK {TAG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
