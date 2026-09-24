"""Hotfix QA 8447 — logo BSC + toggle ocultar panel JSON."""
from __future__ import annotations

import os
import pathlib
import shlex
import time

import paramiko

LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
REMOTE_LAB = "/opt/genesis-cognitive-8447/lab8446_runtime"
FILES = [
    "static/pruebas/index.html",
    "static/pruebas/app.js",
    "static/pruebas/styles.css",
    "static/pruebas/logo-bsc.png",
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
    for rel in FILES:
        local = LAB / rel
        if not local.is_file():
            print(f"MISSING {local}")
            return 1
        tmp = f"/tmp/hotfix_ui_{pathlib.Path(rel).name}_{ts}"
        print(f"PUT {rel}")
        sftp.put(str(local), tmp)
        remote_tmp.append((tmp, f"{REMOTE_LAB}/{rel}"))
    sftp.close()

    def run_sudo(cmd: str) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _stdin, stdout, stderr = client.exec_command(wrapped, timeout=120)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            print(out[-4000:])
        return code, out

    copies = " && ".join(
        f"mkdir -p {shlex.quote(str(pathlib.PurePosixPath(d).parent))} && "
        f"cp -f {shlex.quote(s)} {shlex.quote(d)} && chown genesis:genesis {shlex.quote(d)}"
        for s, d in remote_tmp
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(s)}" for s, _ in remote_tmp)
    code, _ = run_sudo(
        f"test -d {REMOTE_LAB}/static/pruebas || exit 2; {copies} && "
        "ls -la /opt/genesis-cognitive-8447/lab8446_runtime/static/pruebas/logo-bsc.png; "
        "curl -sf -m 8 -o /dev/null -w 'logo_http=%{http_code}\\n' "
        "http://127.0.0.1:8447/pruebas/logo-bsc.png; "
        f"{cleanup}"
    )
    client.close()
    print("OK — UI logo + toggle JSON" if code == 0 else f"FAIL {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
