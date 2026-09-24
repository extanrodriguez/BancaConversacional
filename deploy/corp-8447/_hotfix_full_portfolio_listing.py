"""Hotfix QA 8447 — listado completo de productos (no solo saldos).

1) Backup remoto (tarball) de lab8446 + sibling product_display ANTES de copiar.
2) Copia:
   - lab8446/{models,portfolio_loader,agent,tools}.py → lab8446_runtime
   - product_display.py → sibling_src + Genesis_v2 (espejo)
3) Reinicia 8447, valida health y smoke de listado.

No toca .env, unit systemd, Redis ni :8446.
Requiere SSH_DEPLOY_PASS.
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
REMOTE_LEGACY = f"{REMOTE_PARENT}/Genesis_v2"
SERVICE = "genesis-cognitive-8447.service"

LAB_FILES = [
    "lab8446/models.py",
    "lab8446/portfolio_loader.py",
    "lab8446/agent.py",
    "lab8446/tools.py",
    "lab8446/product_context_service.py",
]
SRC_FILES = [
    "src/genesis_cognitive/context/product_display.py",
]
PORTFOLIO_REL = "data/lab_portfolios/qa_726588_contract_demo.json"

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
BACKUP_TAG = f"full_portfolio_listing_{STAMP}"


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
    for rel in SRC_FILES:
        if not (ROOT / rel).is_file():
            print("MISSING", ROOT / rel)
            return 2
    if not (LAB8446 / PORTFOLIO_REL).is_file():
        print("MISSING", LAB8446 / PORTFOLIO_REL)
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
                print(out[-10000:])
            except UnicodeEncodeError:
                print(out[-10000:].encode("ascii", "replace").decode("ascii"))
        return code, out

    print(f"BACKUP_TAG={BACKUP_TAG}")
    run_sudo(
        "systemctl show genesis-cognitive-8447 -p WorkingDirectory --no-pager; "
        "curl -sf -m 8 http://127.0.0.1:8447/health || true; echo"
    )

    backup_dir = f"{REMOTE_PARENT}/backups/{BACKUP_TAG}"
    bak: list[str] = [
        f"mkdir -p {shlex.quote(backup_dir)}/lab8446 "
        f"{shlex.quote(backup_dir)}/sibling_src "
        f"{shlex.quote(backup_dir)}/Genesis_v2",
    ]
    for rel in LAB_FILES:
        src = f"{REMOTE_LAB}/{rel}"
        bak.append(
            f"if [ -f {shlex.quote(src)} ]; then "
            f"cp -a {shlex.quote(src)} {shlex.quote(backup_dir + '/' + rel)}; "
            f"echo BAK_LAB {rel}; fi"
        )
    for rel in SRC_FILES:
        sub = rel[len("src/") :]
        sib = f"{REMOTE_LAB}/sibling_src/{sub}"
        leg = f"{REMOTE_LEGACY}/{rel}"
        bak.append(
            f"if [ -f {shlex.quote(sib)} ]; then mkdir -p $(dirname {shlex.quote(backup_dir + '/sibling_src/' + sub)}); "
            f"cp -a {shlex.quote(sib)} {shlex.quote(backup_dir + '/sibling_src/' + sub)}; echo BAK_SIB {sub}; fi"
        )
        bak.append(
            f"if [ -f {shlex.quote(leg)} ]; then mkdir -p $(dirname {shlex.quote(backup_dir + '/Genesis_v2/' + rel)}); "
            f"cp -a {shlex.quote(leg)} {shlex.quote(backup_dir + '/Genesis_v2/' + rel)}; echo BAK_LEG {rel}; fi"
        )
    bak.append(
        f"tar -czf {shlex.quote(backup_dir)}.tar.gz -C {shlex.quote(REMOTE_PARENT + '/backups')} {shlex.quote(BACKUP_TAG)} "
        f"&& ls -la {shlex.quote(backup_dir)}.tar.gz && echo BACKUP_OK"
    )
    code_b, out_b = run_sudo(" && ".join(bak), timeout=240)
    if code_b != 0 or "BACKUP_OK" not in out_b:
        print("FAIL backup")
        client.close()
        return 3

    local_bak = ROOT / "backups" / BACKUP_TAG
    local_bak.mkdir(parents=True, exist_ok=True)
    (local_bak / "README.txt").write_text(
        f"Hotfix {BACKUP_TAG}\nRemote: {backup_dir}.tar.gz\n"
        + "\n".join(LAB_FILES + SRC_FILES)
        + "\n",
        encoding="utf-8",
    )

    sftp = client.open_sftp()
    ts = int(time.time())
    remote_tmp: list[tuple[str, str, str]] = []
    for rel in LAB_FILES:
        tmp = f"/tmp/hotfix_fpl_{pathlib.Path(rel).name}_{ts}"
        print(f"PUT {rel} -> {tmp}")
        sftp.put(str(LAB8446 / rel), tmp)
        remote_tmp.append((tmp, "lab", rel))
    for rel in SRC_FILES:
        tmp = f"/tmp/hotfix_fpl_{pathlib.Path(rel).name}_{ts}"
        print(f"PUT {rel} -> {tmp}")
        sftp.put(str(ROOT / rel), tmp)
        remote_tmp.append((tmp, "src", rel))
    pf_tmp = f"/tmp/hotfix_fpl_portfolio_{ts}.json"
    print(f"PUT {PORTFOLIO_REL} -> {pf_tmp}")
    sftp.put(str(LAB8446 / PORTFOLIO_REL), pf_tmp)
    remote_tmp.append((pf_tmp, "portfolio", PORTFOLIO_REL))
    sftp.close()

    copies: list[str] = []
    for tmp, kind, rel in remote_tmp:
        if kind == "lab":
            dst = f"{REMOTE_LAB}/{rel}"
            copies.append(
                f"mkdir -p $(dirname {shlex.quote(dst)}); "
                f"cp -f {shlex.quote(tmp)} {shlex.quote(dst)}; "
                f"chown genesis:genesis {shlex.quote(dst)}; echo COPIED_LAB {rel}"
            )
        elif kind == "portfolio":
            dst = f"{REMOTE_LAB}/{PORTFOLIO_REL}"
            copies.append(
                f"mkdir -p $(dirname {shlex.quote(dst)}); "
                f"cp -f {shlex.quote(tmp)} {shlex.quote(dst)}; "
                f"chown genesis:genesis {shlex.quote(dst)}; echo COPIED_PF {dst}"
            )
            leg_dst = f"{REMOTE_LEGACY}/{PORTFOLIO_REL}"
            copies.append(
                f"mkdir -p $(dirname {shlex.quote(leg_dst)}); "
                f"cp -f {shlex.quote(tmp)} {shlex.quote(leg_dst)}; "
                f"chown genesis:genesis {shlex.quote(leg_dst)}; echo COPIED_PF {leg_dst}"
            )
        else:
            sub = rel[len("src/") :]
            sib_dst = f"{REMOTE_LAB}/sibling_src/{sub}"
            leg_dst = f"{REMOTE_LEGACY}/{rel}"
            copies.append(
                f"if [ -d {shlex.quote(REMOTE_LAB + '/sibling_src/genesis_cognitive')} ]; then "
                f"mkdir -p $(dirname {shlex.quote(sib_dst)}); cp -f {shlex.quote(tmp)} {shlex.quote(sib_dst)}; "
                f"chown genesis:genesis {shlex.quote(sib_dst)}; echo COPIED_SIB {sub}; fi"
            )
            copies.append(
                f"if [ -d {shlex.quote(REMOTE_LEGACY + '/src/genesis_cognitive')} ]; then "
                f"mkdir -p $(dirname {shlex.quote(leg_dst)}); cp -f {shlex.quote(tmp)} {shlex.quote(leg_dst)}; "
                f"chown genesis:genesis {shlex.quote(leg_dst)}; echo COPIED_LEG {rel}; fi"
            )

    cleanup = " ; ".join(f"rm -f {shlex.quote(t)}" for t, _, _ in remote_tmp)
    verify = (
        f"grep -n 'format_full_portfolio_listing' {REMOTE_LAB}/lab8446/portfolio_loader.py | head -2; "
        f"grep -n 'deterministic_portfolio_list' {REMOTE_LAB}/lab8446/agent.py | head -2; "
        f"grep -n 'lab_portfolio_refresh' {REMOTE_LAB}/lab8446/product_context_service.py | head -2; "
        f"grep -n 'interestRateCd' {REMOTE_LAB}/{PORTFOLIO_REL} | head -2"
    )
    code, out = run_sudo(
        f"test -d {REMOTE_LAB}/lab8446 || {{ echo MISSING_LAB; exit 2; }}; "
        f"{' && '.join(copies)} && {verify}; "
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
    if "active" not in out:
        client.close()
        return 5

    # Smoke: modo determinista + tasa/corte/intereses (no solo saldos)
    code2, out2 = run_sudo(
        r"""python3 - <<'PY'
import json, urllib.request, re

req = urllib.request.Request(
    'http://127.0.0.1:8447/turn',
    data=json.dumps({
        'conversation_id': 'smoke-full-list-v2',
        'question': 'lista mis productos',
        'customer_id': '726588',
        'debug': True,
    }).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=90) as r:
    body = json.loads(r.read().decode())
reply = body.get('reply') or ''
dbg = body.get('debug') or {}
mode = dbg.get('mode')
print('MODE', mode)
print('REPLY_LEN', len(reply))
checks = {
    'mode_det': mode == 'deterministic_portfolio_list',
    'tasa': 'Tasa de interés' in reply or bool(re.search(r'Tasa', reply)),
    'intereses': 'Intereses acumulados' in reply,
    'corte': 'Fecha de corte' in reply,
    'limite': 'Límite de crédito' in reply or 'Limite de credito' in reply,
    'expiracion': 'Fecha de expiración' in reply or 'expiraci' in reply.lower(),
}
print('CHECKS', checks)
print('REPLY_HEAD', reply[:1200].encode('ascii','replace').decode('ascii'))
ok = checks['mode_det'] and checks['tasa'] and (checks['intereses'] or checks['corte'])
print('SMOKE_OK' if ok else 'SMOKE_FAIL')
PY"""
    )
    client.close()
    if code2 != 0 or "SMOKE_OK" not in out2:
        print("FAIL smoke")
        return 6
    print(f"OK — full portfolio listing en 8447 (backup {BACKUP_TAG})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
