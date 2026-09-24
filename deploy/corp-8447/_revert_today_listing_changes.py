"""Restaura lab8446 en 8447 al estado PREVIO a los cambios de listado (hoy).

Fuente: backup remoto full_portfolio_listing_20260924_112029
También trae esos archivos al workspace local.
"""
from __future__ import annotations

import os
import pathlib
import shlex
import sys
from datetime import datetime, timezone

import paramiko

ROOT = pathlib.Path(__file__).resolve().parents[2]
LAB8446 = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
REMOTE_PARENT = "/opt/genesis-cognitive-8447"
REMOTE_LAB = f"{REMOTE_PARENT}/lab8446_runtime"
BACKUP_SRC = f"{REMOTE_PARENT}/backups/full_portfolio_listing_20260924_112029"
SERVICE = "genesis-cognitive-8447.service"

LAB_FILES = [
    "lab8446/models.py",
    "lab8446/portfolio_loader.py",
    "lab8446/agent.py",
    "lab8446/tools.py",
]

# product_context_service no estaba en ese backup; se restaura lógica simple aparte vía local
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
SAFE_TAG = f"pre_revert_snapshot_{STAMP}"


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
    print(f"Conectando {user}@{host}...")
    client.connect(host, username=user, password=password, timeout=40, look_for_keys=False, allow_agent=False)

    def run(cmd: str, timeout: int = 300) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _, stdout, stderr = client.exec_command(wrapped, timeout=timeout)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            print(out[-12000:])
        return code, out

    # Snapshot actual antes de revertir
    safe = f"{REMOTE_PARENT}/backups/{SAFE_TAG}"
    run(
        f"mkdir -p {safe}/lab8446 && "
        + " && ".join(
            f"cp -a {REMOTE_LAB}/{rel} {safe}/{rel}" for rel in LAB_FILES + ["lab8446/product_context_service.py"]
        )
        + f" && tar -czf {safe}.tar.gz -C {REMOTE_PARENT}/backups {SAFE_TAG} && echo SAFE_OK"
    )

    # Verificar backup fuente
    code, out = run(
        f"test -d {BACKUP_SRC}/lab8446 && ls -la {BACKUP_SRC}/lab8446 && echo SRC_OK"
    )
    if code != 0 or "SRC_OK" not in out:
        # intentar expandir tarball
        run(
            f"mkdir -p {BACKUP_SRC} && "
            f"tar -xzf {BACKUP_SRC}.tar.gz -C {REMOTE_PARENT}/backups && "
            f"ls -la {BACKUP_SRC}/lab8446 && echo SRC_OK"
        )

    # Restaurar en runtime
    copies = " && ".join(
        f"cp -a {BACKUP_SRC}/{rel} {REMOTE_LAB}/{rel} && chown genesis:genesis {REMOTE_LAB}/{rel} && echo RESTORED {rel}"
        for rel in LAB_FILES
    )
    code, out = run(
        f"{copies} && systemctl restart {SERVICE}; sleep 6; "
        f"systemctl is-active {SERVICE}; curl -sf -m 10 http://127.0.0.1:8447/health; echo; echo REVERT_DEPLOY_OK"
    )
    if code != 0 or "REVERT_DEPLOY_OK" not in out:
        client.close()
        return 4

    # Descargar al workspace local
    sftp = client.open_sftp()
    local_restore = ROOT / "backups" / f"restored_from_{STAMP}"
    local_restore.mkdir(parents=True, exist_ok=True)
    for rel in LAB_FILES:
        remote = f"{REMOTE_LAB}/{rel}"
        dest_lab = LAB8446 / rel
        dest_bak = local_restore / rel.replace("/", "_")
        print(f"GET {remote}")
        sftp.get(remote, str(dest_bak))
        dest_lab.parent.mkdir(parents=True, exist_ok=True)
        sftp.get(remote, str(dest_lab))
    # también product_display sibling si existe en backup
    for sub in (
        "sibling_src/genesis_cognitive/context/product_display.py",
        "Genesis_v2/src/genesis_cognitive/context/product_display.py",
    ):
        rpath = f"{BACKUP_SRC}/{sub}"
        try:
            sftp.stat(rpath)
        except OSError:
            continue
        print(f"GET {rpath}")
        local_name = local_restore / sub.replace("/", "_")
        sftp.get(rpath, str(local_name))
        if "sibling_src" in sub:
            dst = ROOT / "src/genesis_cognitive/context/product_display.py"
            sftp.get(rpath, str(dst))
            # mirror to remote sibling + legacy
            run(
                f"cp -a {BACKUP_SRC}/{sub} {REMOTE_LAB}/sibling_src/genesis_cognitive/context/product_display.py; "
                f"cp -a {BACKUP_SRC}/Genesis_v2/src/genesis_cognitive/context/product_display.py "
                f"{REMOTE_PARENT}/Genesis_v2/src/genesis_cognitive/context/product_display.py 2>/dev/null || true; "
                f"systemctl restart {SERVICE}; sleep 4; echo DISPLAY_RESTORED"
            )
    sftp.close()
    client.close()
    print(f"OK revert desde {BACKUP_SRC}; snapshot actual en {SAFE_TAG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
