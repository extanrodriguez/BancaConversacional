"""Deploy containers 8448 via SSH password (env SSH_DEPLOY_PASS)."""
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
    remote_zip = "/tmp/genesis_corp_8448.zip"

    if not zip_local.is_file():
        print(f"ERROR: falta {zip_local}")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host}...")
    client.connect(host, username=user, password=password, timeout=30, look_for_keys=False, allow_agent=False)
    print("SSH OK")

    sftp = client.open_sftp()
    print(f"Subiendo -> {remote_zip}")
    sftp.put(str(zip_local), remote_zip)
    sftp.close()

    def run(cmd: str, *, sudo: bool = False) -> tuple[int, str]:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=1200)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        text = (out + err).strip()
        if text:
            safe = text[-8000:].encode("ascii", errors="replace").decode("ascii")
            print(safe)
        return code, text

    run("hostname && whoami && docker --version || true")

    deploy_inner = (
        "mkdir -p /opt/genesis-cognitive-8448/Genesis_v2 && "
        "cd /opt/genesis-cognitive-8448/Genesis_v2 && "
        "unzip -oq /tmp/genesis_corp_8448.zip && "
        "find . -name '*.sh' -exec sed -i 's/\\r$//' {} \\; && "
        # Heredar secretos si faltan
        "if [ ! -f .env ]; then "
        "  if [ -f /opt/genesis-cognitive-8447/Genesis_v2/.env ]; then cp /opt/genesis-cognitive-8447/Genesis_v2/.env .env; "
        "  elif [ -f /opt/genesis-cognitive-8446/Genesis_v2/.env ]; then cp /opt/genesis-cognitive-8446/Genesis_v2/.env .env; fi; "
        "fi && "
        "bash deploy/corp-8448/deploy_8448.sh"
    )
    code, _ = run(deploy_inner, sudo=True)

    if code == 0:
        run("curl -sS -m 8 http://127.0.0.1:8448/health || true")
        run("curl -sS -m 5 -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:8448/pruebas || true")

    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
