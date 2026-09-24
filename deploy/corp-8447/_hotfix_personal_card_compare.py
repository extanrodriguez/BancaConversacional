"""Hotfix QA 8447 — comparación personal de tarjetas (Full Car vs Joven).

Sube a /tmp y copia con sudo (el árbol /opt no es escribible por SFTP directo).
Requiere SSH_DEPLOY_PASS o %TEMP%/genesis_ssh_pass_once.txt
"""
from __future__ import annotations

import os
import pathlib
import shlex
import sys
import time

import paramiko

ROOT = pathlib.Path(__file__).resolve().parents[2]
REMOTE_APP = "/opt/genesis-cognitive-8447/Genesis_v2"
FILES = [
    "src/genesis_cognitive/brain/plan_interpreter.py",
    "src/genesis_cognitive/brain/azure_plan_adapter.py",
    "src/genesis_cognitive/brain/plan_executor.py",
    "src/genesis_cognitive/context/app_channel.py",
]


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

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host}...")
    client.connect(
        host, username=user, password=password, timeout=40,
        look_for_keys=False, allow_agent=False,
    )
    print("SSH OK")

    sftp = client.open_sftp()
    remote_tmp_files: list[tuple[str, str]] = []
    for rel in FILES:
        local = ROOT / rel
        if not local.is_file():
            print(f"MISSING {rel}")
            return 1
        tmp = f"/tmp/hotfix_{pathlib.Path(rel).name}_{int(time.time())}"
        print(f"PUT {rel} -> {tmp}")
        sftp.put(str(local), tmp)
        remote_tmp_files.append((tmp, f"{REMOTE_APP}/{rel}"))
    sftp.close()

    def run_sudo(cmd: str) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _stdin, stdout, stderr = client.exec_command(wrapped, timeout=180)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
        out = out.replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            print(out[-4000:])
        return code, out

    copies = " && ".join(
        f"cp -f {shlex.quote(src)} {shlex.quote(dst)} && chown genesis:genesis {shlex.quote(dst)}"
        for src, dst in remote_tmp_files
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(src)}" for src, _ in remote_tmp_files)
    code, _ = run_sudo(
        f"{copies} && "
        "systemctl restart genesis-cognitive-8447.service; sleep 4; "
        "systemctl is-active genesis-cognitive-8447.service; "
        "curl -sf -m 8 http://127.0.0.1:8447/health; echo; "
        "curl -sf -m 8 http://127.0.0.1:8447/ready; echo; "
        f"{cleanup}"
    )
    client.close()
    if code != 0:
        print(f"FAIL exit={code}")
        return code
    print("OK — hotfix personal card compare aplicado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
