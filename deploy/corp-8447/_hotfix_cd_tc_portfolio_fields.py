"""Hotfix QA 8447 — CD tasa/intereses + TC corte/balances/expiración + portafolio lab.

Backup remoto previo → copia quirúrgica a sibling_src + Genesis_v2 + lab portfolios.
No toca arquitectura, Redis, .env ni :8446.
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

SRC_FILES = [
    "src/genesis_cognitive/context/product_context_service.py",
    "src/genesis_cognitive/context/response_formatting.py",
    "src/genesis_cognitive/router/final_response_agent.py",
    "src/genesis_cognitive/agents/product_context_tools.py",
]

PORTFOLIO_REL = "data/lab_portfolios/qa_726588_contract_demo.json"

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
BACKUP_TAG = f"cd_tc_portfolio_fields_{STAMP}"


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

    for rel in SRC_FILES:
        if not (ROOT / rel).is_file():
            print("MISSING", rel)
            return 2
    if not (ROOT / PORTFOLIO_REL).is_file():
        print("MISSING", PORTFOLIO_REL)
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
                print(out[-8000:])
            except UnicodeEncodeError:
                print(out[-8000:].encode("ascii", "replace").decode("ascii"))
        return code, out

    print(f"BACKUP_TAG={BACKUP_TAG}")
    run_sudo(
        "systemctl show genesis-cognitive-8447 -p WorkingDirectory --no-pager; "
        "curl -sf -m 8 http://127.0.0.1:8447/health || true; echo"
    )

    backup_dir = f"{REMOTE_PARENT}/backups/{BACKUP_TAG}"
    bak: list[str] = [
        f"mkdir -p {shlex.quote(backup_dir)}/sibling_src {shlex.quote(backup_dir)}/Genesis_v2 "
        f"{shlex.quote(backup_dir)}/lab_portfolios",
    ]
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
    for pf in (
        f"{REMOTE_LAB}/{PORTFOLIO_REL}",
        f"{REMOTE_LEGACY}/{PORTFOLIO_REL}",
        f"{REMOTE_LAB}/data/lab_portfolios/qa_726588_contract_demo.json",
    ):
        bak.append(
            f"if [ -f {shlex.quote(pf)} ]; then "
            f"cp -a {shlex.quote(pf)} {shlex.quote(backup_dir)}/lab_portfolios/$(basename {shlex.quote(pf)}).$(echo {shlex.quote(pf)} | tr '/' '_'); "
            f"echo BAK_PF {pf}; fi"
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
        + "\n".join(SRC_FILES)
        + f"\n{PORTFOLIO_REL}\n",
        encoding="utf-8",
    )

    sftp = client.open_sftp()
    ts = int(time.time())
    remote_tmp: list[tuple[str, str, str]] = []  # tmp, kind, rel
    for rel in SRC_FILES:
        tmp = f"/tmp/hotfix_cdtc_{pathlib.Path(rel).name}_{ts}"
        print(f"PUT {rel} -> {tmp}")
        sftp.put(str(ROOT / rel), tmp)
        remote_tmp.append((tmp, "src", rel))
    pf_tmp = f"/tmp/hotfix_cdtc_portfolio_{ts}.json"
    print(f"PUT {PORTFOLIO_REL} -> {pf_tmp}")
    sftp.put(str(ROOT / PORTFOLIO_REL), pf_tmp)
    remote_tmp.append((pf_tmp, "portfolio", PORTFOLIO_REL))
    sftp.close()

    copies: list[str] = []
    for tmp, kind, rel in remote_tmp:
        if kind == "src":
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
        else:
            for dst in (
                f"{REMOTE_LAB}/{PORTFOLIO_REL}",
                f"{REMOTE_LEGACY}/{PORTFOLIO_REL}",
            ):
                copies.append(
                    f"mkdir -p $(dirname {shlex.quote(dst)}); "
                    f"cp -f {shlex.quote(tmp)} {shlex.quote(dst)}; "
                    f"chown genesis:genesis {shlex.quote(dst)}; echo COPIED_PF {dst}"
                )

    cleanup = " ; ".join(f"rm -f {shlex.quote(t)}" for t, _, _ in remote_tmp)
    verify = (
        f"grep -n 'interest_amount' {REMOTE_LAB}/sibling_src/genesis_cognitive/context/product_context_service.py | head -3; "
        f"grep -n 'Balance actual' {REMOTE_LAB}/sibling_src/genesis_cognitive/context/response_formatting.py | head -3; "
        f"grep -n 'Visa Bravo Santa Cruz' {REMOTE_LAB}/{PORTFOLIO_REL} | head -2; "
        f"grep -n '3515.196096' {REMOTE_LAB}/{PORTFOLIO_REL} | head -2"
    )
    code, out = run_sudo(
        f"{' && '.join(copies)} && {verify}; "
        f"systemctl restart {SERVICE}; sleep 6; "
        f"systemctl is-active {SERVICE}; "
        "curl -sf -m 12 http://127.0.0.1:8447/health; echo; "
        "curl -sf -m 12 http://127.0.0.1:8447/ready; echo; "
        f"{cleanup}; echo DEPLOY_OK BACKUP={backup_dir}.tar.gz"
    )
    client.close()
    if code != 0 or "DEPLOY_OK" not in out:
        print(f"FAIL exit={code}")
        return code or 4
    if "active" not in out:
        return 5
    print(f"OK — CD/TC portfolio fields en 8447 (backup {BACKUP_TAG})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
