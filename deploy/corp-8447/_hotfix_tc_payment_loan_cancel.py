"""Hotfix QA 8447 — fecha pago/expiración TC + cancelar el préstamo.

1) Backup remoto (carpeta + tarball) de los archivos tocados ANTES de copiar.
2) Copia solo módulos cognitivos a:
   - lab8446_runtime/sibling_src (runtime activo)
   - Genesis_v2/src (espejo)
3) Reinicia 8447 y valida health/ready.

No toca :8446, Redis, Foundry/.env, unit systemd ni lab8446/*.py.
Requiere SSH_DEPLOY_PASS o %TEMP%/genesis_ssh_pass_once.txt
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
REMOTE_PARENT = "/opt/genesis-cognitive-8447"
REMOTE_LAB = f"{REMOTE_PARENT}/lab8446_runtime"
REMOTE_LEGACY = f"{REMOTE_PARENT}/Genesis_v2"
SERVICE = "genesis-cognitive-8447.service"

FILES = [
    "src/genesis_cognitive/context/core_portfolio_mapper.py",
    "src/genesis_cognitive/brain/plan_interpreter.py",
    "src/genesis_cognitive/router/final_response_agent.py",
    "src/genesis_cognitive/router/field_guardrails.py",
    "src/genesis_cognitive/brain/grounded_executor.py",
    "src/genesis_cognitive/context/app_channel.py",
    "src/genesis_cognitive/context/query_spec.py",
    "src/genesis_cognitive/context/product_context_service.py",
    "src/genesis_cognitive/brain/core_facts_catalog.py",
    "src/genesis_cognitive/brain/azure_plan_adapter.py",
    "src/genesis_cognitive/brain/azure_plan_turn.py",
]

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
BACKUP_TAG = f"tc_payment_loan_cancel_{STAMP}"


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
        print("ERROR: define SSH_DEPLOY_PASS")
        raise SystemExit(1)
    return pw


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")

    missing = [r for r in FILES if not (ROOT / r).is_file()]
    if missing:
        print("MISSING", missing)
        return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host}...")
    client.connect(
        host,
        username=user,
        password=password,
        timeout=40,
        look_for_keys=False,
        allow_agent=False,
    )
    print("SSH OK")

    def run_sudo(cmd: str, timeout: int = 300) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _stdin, stdout, stderr = client.exec_command(wrapped, timeout=timeout)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
        out = out.replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            try:
                print(out[-8000:])
            except UnicodeEncodeError:
                print(out[-8000:].encode("ascii", "replace").decode("ascii"))
        return code, out

    print(f"BACKUP_TAG={BACKUP_TAG}")
    run_sudo(
        "systemctl show genesis-cognitive-8447 -p WorkingDirectory -p FragmentPath --no-pager; "
        "curl -sf -m 8 http://127.0.0.1:8447/health || true; echo; "
        f"ls -ld {REMOTE_LAB}/sibling_src/genesis_cognitive "
        f"{REMOTE_LEGACY}/src/genesis_cognitive 2>/dev/null || true"
    )

    backup_dir = f"{REMOTE_PARENT}/backups/{BACKUP_TAG}"
    backup_cmds = [
        f"mkdir -p {shlex.quote(backup_dir)}/sibling_src {shlex.quote(backup_dir)}/Genesis_v2",
        f"echo BACKUP_DIR={backup_dir}",
    ]
    for rel in FILES:
        sub = rel[len("src/") :]  # genesis_cognitive/...
        sib = f"{REMOTE_LAB}/sibling_src/{sub}"
        leg = f"{REMOTE_LEGACY}/{rel}"
        sib_dst = f"{backup_dir}/sibling_src/{sub}"
        leg_dst = f"{backup_dir}/Genesis_v2/{rel}"
        backup_cmds.append(
            f"if [ -f {shlex.quote(sib)} ]; then "
            f"mkdir -p $(dirname {shlex.quote(sib_dst)}); "
            f"cp -a {shlex.quote(sib)} {shlex.quote(sib_dst)}; "
            f"echo BAK_SIB {sub}; fi"
        )
        backup_cmds.append(
            f"if [ -f {shlex.quote(leg)} ]; then "
            f"mkdir -p $(dirname {shlex.quote(leg_dst)}); "
            f"cp -a {shlex.quote(leg)} {shlex.quote(leg_dst)}; "
            f"echo BAK_LEG {rel}; fi"
        )
    backup_cmds.append(
        f"tar -czf {shlex.quote(backup_dir)}.tar.gz "
        f"-C {shlex.quote(REMOTE_PARENT + '/backups')} {shlex.quote(BACKUP_TAG)} "
        f"&& ls -la {shlex.quote(backup_dir)}.tar.gz "
        f"&& echo BACKUP_OK"
    )

    code_b, out_b = run_sudo(" && ".join(backup_cmds), timeout=240)
    if code_b != 0 or "BACKUP_OK" not in out_b:
        print("FAIL backup remoto")
        client.close()
        return 3

    local_bak = ROOT / "backups" / BACKUP_TAG
    local_bak.mkdir(parents=True, exist_ok=True)
    (local_bak / "README.txt").write_text(
        f"Hotfix {BACKUP_TAG}\n"
        f"Remote tarball: {backup_dir}.tar.gz\n"
        f"Files:\n" + "\n".join(FILES) + "\n\n"
        "Rollback (en la VM):\n"
        f"  sudo tar -xzf {backup_dir}.tar.gz -C {REMOTE_PARENT}/backups\n"
        f"  # restaurar desde {backup_dir}/sibling_src y .../Genesis_v2\n"
        f"  sudo systemctl restart {SERVICE}\n",
        encoding="utf-8",
    )
    print(f"LOCAL_NOTE {local_bak}")

    sftp = client.open_sftp()
    ts = int(time.time())
    remote_tmp: list[tuple[str, str]] = []
    for rel in FILES:
        local = ROOT / rel
        tmp = f"/tmp/hotfix_tc_{pathlib.Path(rel).name}_{ts}"
        print(f"PUT {rel} -> {tmp}")
        sftp.put(str(local), tmp)
        remote_tmp.append((tmp, rel))
    sftp.close()

    copy_bits: list[str] = []
    for tmp, rel in remote_tmp:
        sub = rel[len("src/") :]
        sib_dst = f"{REMOTE_LAB}/sibling_src/{sub}"
        leg_dst = f"{REMOTE_LEGACY}/{rel}"
        copy_bits.append(
            f"if [ -d {shlex.quote(REMOTE_LAB + '/sibling_src/genesis_cognitive')} ]; then "
            f"mkdir -p $(dirname {shlex.quote(sib_dst)}); "
            f"cp -f {shlex.quote(tmp)} {shlex.quote(sib_dst)}; "
            f"chown genesis:genesis {shlex.quote(sib_dst)}; "
            f"echo COPIED_SIB {sub}; fi"
        )
        copy_bits.append(
            f"if [ -d {shlex.quote(REMOTE_LEGACY + '/src/genesis_cognitive')} ]; then "
            f"mkdir -p $(dirname {shlex.quote(leg_dst)}); "
            f"cp -f {shlex.quote(tmp)} {shlex.quote(leg_dst)}; "
            f"chown genesis:genesis {shlex.quote(leg_dst)}; "
            f"echo COPIED_LEG {rel}; fi"
        )

    cleanup = " ; ".join(f"rm -f {shlex.quote(tmp)}" for tmp, _ in remote_tmp)
    verify = (
        f"grep -n 'maturityDate' "
        f"{REMOTE_LAB}/sibling_src/genesis_cognitive/context/core_portfolio_mapper.py 2>/dev/null | head -5; "
        f"grep -n 'cancelar el prestamo' "
        f"{REMOTE_LAB}/sibling_src/genesis_cognitive/brain/plan_interpreter.py 2>/dev/null | head -3; "
        f"grep -n 'maturityDate' "
        f"{REMOTE_LEGACY}/src/genesis_cognitive/context/core_portfolio_mapper.py 2>/dev/null | head -5; "
        f"grep -n 'cancelar el prestamo' "
        f"{REMOTE_LEGACY}/src/genesis_cognitive/brain/plan_interpreter.py 2>/dev/null | head -3"
    )

    code, out = run_sudo(
        f"{' && '.join(copy_bits)} && "
        f"{verify}; "
        f"systemctl restart {SERVICE}; sleep 6; "
        f"systemctl is-active {SERVICE}; "
        "curl -sf -m 12 http://127.0.0.1:8447/health; echo; "
        "curl -sf -m 12 http://127.0.0.1:8447/ready; echo; "
        f"{cleanup}; "
        f"echo DEPLOY_OK BACKUP={backup_dir}.tar.gz"
    )
    client.close()

    if code != 0 or "DEPLOY_OK" not in out:
        print(f"FAIL exit={code}")
        return code or 4
    if "active" not in out:
        print("WARN: service may not be active")
        return 5
    print(f"OK — hotfix en 8447 (backup {BACKUP_TAG})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
