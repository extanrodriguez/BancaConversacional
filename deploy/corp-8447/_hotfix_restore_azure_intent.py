"""Hotfix QA 8447 — restaurar interpretación Azure + Redis con campos de negocio.

Revierte el bypass determinista de listado. Mantiene:
- mapper Core → campos de negocio en Redis
- tool que entrega el registro completo
- instrucciones para que Azure filtre por intención (typos/tarjeta/etc.)

No toca arquitectura Foundry, .env, Redis keys ni :8446.
"""
from __future__ import annotations

import os
import pathlib
import shlex
import sys
import time
from datetime import datetime, timezone

import paramiko

ROOT = pathlib.Path(__file__).resolve().parents[2]
LAB8446 = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
REMOTE_PARENT = "/opt/genesis-cognitive-8447"
REMOTE_LAB = f"{REMOTE_PARENT}/lab8446_runtime"
SERVICE = "genesis-cognitive-8447.service"

LAB_FILES = [
    "lab8446/agent.py",
    "lab8446/tools.py",
    "lab8446/models.py",
    "lab8446/portfolio_loader.py",
    "lab8446/product_context_service.py",
]

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
BACKUP_TAG = f"restore_azure_intent_{STAMP}"


def _password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = pathlib.Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
            try:
                once.unlink()
            except OSError:
                pass
    if not pw:
        raise SystemExit("ERROR: define SSH_DEPLOY_PASS")
    return pw


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")

    for rel in LAB_FILES:
        if not (LAB8446 / rel).is_file():
            print("MISSING", LAB8446 / rel)
            return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host}...")
    client.connect(
        host, username=user, password=password, timeout=40,
        look_for_keys=False, allow_agent=False,
    )
    print("SSH OK")

    def run_sudo(cmd: str, timeout: int = 300) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _i, stdout, stderr = client.exec_command(wrapped, timeout=timeout)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            try:
                print(out[-12000:])
            except UnicodeEncodeError:
                print(out[-12000:].encode("ascii", "replace").decode("ascii"))
        return code, out

    print(f"BACKUP_TAG={BACKUP_TAG}")
    backup_dir = f"{REMOTE_PARENT}/backups/{BACKUP_TAG}"
    bak = [
        f"mkdir -p {shlex.quote(backup_dir)}/lab8446",
    ]
    for rel in LAB_FILES:
        src = f"{REMOTE_LAB}/{rel}"
        bak.append(
            f"if [ -f {shlex.quote(src)} ]; then "
            f"mkdir -p $(dirname {shlex.quote(backup_dir + '/' + rel)}); "
            f"cp -a {shlex.quote(src)} {shlex.quote(backup_dir + '/' + rel)}; "
            f"echo BAK_LAB {rel}; fi"
        )
    bak.append(
        f"tar -czf {shlex.quote(backup_dir)}.tar.gz -C {shlex.quote(REMOTE_PARENT + '/backups')} "
        f"{shlex.quote(BACKUP_TAG)} && ls -la {shlex.quote(backup_dir)}.tar.gz && echo BACKUP_OK"
    )
    code_b, out_b = run_sudo(" && ".join(bak), timeout=240)
    if code_b != 0 or "BACKUP_OK" not in out_b:
        print("FAIL backup")
        client.close()
        return 3

    local_bak = ROOT / "backups" / BACKUP_TAG
    local_bak.mkdir(parents=True, exist_ok=True)
    (local_bak / "README.txt").write_text(
        f"Hotfix {BACKUP_TAG}\nRemote: {backup_dir}.tar.gz\n" + "\n".join(LAB_FILES) + "\n",
        encoding="utf-8",
    )

    sftp = client.open_sftp()
    ts = int(time.time())
    remote_tmp: list[tuple[str, str]] = []
    for rel in LAB_FILES:
        tmp = f"/tmp/hotfix_rai_{pathlib.Path(rel).name}_{ts}"
        print(f"PUT {rel}")
        sftp.put(str(LAB8446 / rel), tmp)
        remote_tmp.append((tmp, f"{REMOTE_LAB}/{rel}"))
    sftp.close()

    copies = " && ".join(
        f"cp -f {shlex.quote(s)} {shlex.quote(d)} && chown genesis:genesis {shlex.quote(d)} && echo COPIED {d}"
        for s, d in remote_tmp
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(s)}" for s, _ in remote_tmp)
    verify = (
        f"! grep -n 'deterministic_portfolio_list' {REMOTE_LAB}/lab8446/agent.py || "
        f"grep -c 'deterministic_portfolio_list' {REMOTE_LAB}/lab8446/agent.py; "
        f"grep -n 'public_dict(None)' {REMOTE_LAB}/lab8446/product_context_service.py | head -2; "
        f"grep -n 'cuanto e k debo' {REMOTE_LAB}/lab8446/tools.py | head -2"
    )
    code, out = run_sudo(
        f"test -d {REMOTE_LAB}/lab8446 || exit 2; {copies} && {verify}; "
        f"systemctl restart {SERVICE}; sleep 6; "
        f"systemctl is-active {SERVICE}; "
        "curl -sf -m 12 http://127.0.0.1:8447/health; echo; "
        "curl -sf -m 12 http://127.0.0.1:8447/ready; echo; "
        f"{cleanup}; echo DEPLOY_OK BACKUP={backup_dir}.tar.gz"
    )
    if code != 0 or "DEPLOY_OK" not in out:
        print(f"FAIL deploy exit={code}")
        client.close()
        return code or 4

    code2, out2 = run_sudo(
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

# 1) Intención tarjeta con typo — NO debe listar todo el portafolio
b1 = turn('cuanto e k debo d la tarjeta y cuando me toca pagar', 'smoke-tc-debt')
r1 = b1.get('reply') or ''
d1 = b1.get('debug') or {}
mode1 = d1.get('mode')
tools1 = d1.get('azure_chose_tools') or []
print('TC_MODE', mode1)
print('TC_TOOLS', tools1)
print('TC_ARGS', (d1.get('tool_calls') or [{}])[0].get('args'))
print('TC_REPLY', r1[:700].encode('ascii','replace').decode('ascii'))
mentions_accounts = bool(re.search(r'Cuenta de Ahorros|Dep[oó]sito a plazo|Pr[eé]stamo', r1, re.I))
mentions_cards = bool(re.search(r'tarjeta|Visa|Joven|Multicredito|Bravo|adeud|debo|pago', r1, re.I))
has_refusal = 'No puedo proporcionar' in r1
tc_ok = mode1 != 'deterministic_portfolio_list' and not has_refusal and mentions_cards and not mentions_accounts
print('TC_CHECKS', {
    'not_deterministic': mode1 != 'deterministic_portfolio_list',
    'mentions_cards': mentions_cards,
    'no_full_portfolio': not mentions_accounts,
    'no_refusal': not has_refusal,
})
print('TC_OK' if tc_ok else 'TC_FAIL')

# 2) Lista completa — Azure responde (no bypass), pero tool debe traer campos ricos
b2 = turn('lista mis productos', 'smoke-list-azure')
r2 = b2.get('reply') or ''
d2 = b2.get('debug') or {}
print('LIST_MODE', d2.get('mode'))
print('LIST_LEN', len(r2))
rich = bool(re.search(r'tasa|inter[eé]s|corte|l[ií]mite|cuota|vencim', r2, re.I))
print('LIST_RICH', rich)
print('LIST_HEAD', r2[:500].encode('ascii','replace').decode('ascii'))
print('LIST_OK' if d2.get('mode') != 'deterministic_portfolio_list' else 'LIST_FAIL_STILL_DET')
print('SMOKE_OK' if tc_ok and d2.get('mode') != 'deterministic_portfolio_list' else 'SMOKE_FAIL')
PY"""
    )
    client.close()
    if code2 != 0 or "SMOKE_OK" not in out2:
        print("FAIL smoke")
        return 6
    print(f"OK — Azure intent restaurado (backup {BACKUP_TAG})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
