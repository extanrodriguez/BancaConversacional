"""Deploy one-shot via SSH password (env SSH_DEPLOY_PASS). No guardar contraseña en disco.

Incluye Fase 1: FAQ overlay + env anti-escalación institucional en 8447.
"""
from __future__ import annotations

import os
import pathlib
import shlex
import sys

import paramiko


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    if not password:
        print("ERROR: define SSH_DEPLOY_PASS")
        return 1

    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    zip_local = pathlib.Path(__file__).resolve().parents[1] / "corp-8446" / "dist" / "genesis_corp_8446.zip"
    remote_zip = "/tmp/genesis_corp_8447.zip"

    if not zip_local.is_file():
        print(f"ERROR: falta {zip_local} — ejecuta deploy/corp-8446/build_corp_package.py")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host}...")
    client.connect(host, username=user, password=password, timeout=30, look_for_keys=False, allow_agent=False)
    print("SSH OK")

    sftp = client.open_sftp()
    print(f"Subiendo -> {remote_zip} ({zip_local.stat().st_size / 1e6:.1f} MB)")
    sftp.put(str(zip_local), remote_zip)
    sftp.close()

    def run(cmd: str, *, sudo: bool = False) -> tuple[int, str]:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=900)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        text = (out + err).strip()
        if text:
            # Windows cp1252 no soporta flechas/unicode del log remoto
            try:
                print(text[-6000:])
            except UnicodeEncodeError:
                print(text[-6000:].encode("ascii", "replace").decode("ascii"))
        return code, text

    run("hostname && whoami")
    run("curl -sS -m 5 http://127.0.0.1:8446/health || true")
    run("curl -sS -m 5 http://127.0.0.1:8447/health || true")

    deploy_inner = (
        "mkdir -p /opt/genesis-cognitive-8447/Genesis_v2 && "
        "cd /opt/genesis-cognitive-8447/Genesis_v2 && "
        "unzip -oq /tmp/genesis_corp_8447.zip && "
        "find . -name '*.sh' -exec sed -i 's/\\r$//' {} \\; && "
        "bash deploy/corp-8447/deploy_8447.sh"
    )
    code, _ = run(deploy_inner, sudo=True)

    if code == 0:
        run(
            "test -f /opt/genesis-cognitive-8447/Genesis_v2/data/kb_faq_overlay_fase1.json "
            "&& echo OVERLAY_OK"
        )
        run(
            "grep -E 'GENESIS_FAQ_|GENESIS_RAG_NO_HUMAN|GENESIS_FOUNDRY|GENESIS_KB_CONFIDENCE|AZURE_SEARCH_INDEX' "
            "/opt/genesis-cognitive-8447/Genesis_v2/.env || true"
        )
        run("curl -sS -m 5 http://127.0.0.1:8447/health")
        run("curl -sS -m 5 http://192.168.150.5:8447/health || true")
        run("curl -sS -m 5 http://127.0.0.1:8446/health")
        run("grep -E '^GENESIS_HOST=' /opt/genesis-cognitive-8447/Genesis_v2/.env || true")
        print(f"Deploy 8447 OK — publica http://{host}:8447/pruebas | privada http://192.168.150.5:8447/pruebas")

    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
