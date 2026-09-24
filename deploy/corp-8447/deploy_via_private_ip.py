"""Deploy 8447 via IP privada (VNet). Uso desde una PC/VPN que alcance 192.168.150.5.

  $env:SSH_DEPLOY_PASS = \"...\"
  $env:SSH_HOST = \"192.168.150.5\"
  .\\.venv\\Scripts\\python.exe deploy\\corp-8447\\deploy_ssh_password.py
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

    host = os.environ.get("SSH_HOST", "192.168.150.5")
    user = os.environ.get("SSH_USER", "genesis")
    zip_local = (
        pathlib.Path(__file__).resolve().parents[1]
        / "corp-8446"
        / "dist"
        / "genesis_corp_8446.zip"
    )
    remote_zip = "/tmp/genesis_corp_8447.zip"

    if not zip_local.is_file():
        print(f"ERROR: falta {zip_local} — ejecuta deploy/corp-8446/build_corp_package.py")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host}...")
    client.connect(
        host,
        username=user,
        password=password,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
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
            print(text[-8000:])
        return code, text

    deploy_inner = (
        "mkdir -p /opt/genesis-cognitive-8447/Genesis_v2 && "
        "cd /opt/genesis-cognitive-8447/Genesis_v2 && "
        "unzip -oq /tmp/genesis_corp_8447.zip && "
        "find . -name '*.sh' -exec sed -i 's/\\r$//' {} \\; && "
        "bash deploy/corp-8447/deploy_8447.sh"
    )
    code, _ = run(deploy_inner, sudo=True)

    if code == 0:
        run("curl -sS -m 5 http://127.0.0.1:8447/health || true")
        run(
            "curl -sS -m 8 -o /tmp/wh.json -w 'http=%{http_code}\\n' "
            "-X POST http://127.0.0.1:8447/orch/webhook/chat "
            "-H 'Content-Type: application/json' -H 'ClientId: 726588' "
            "-d '{\"question\":\"hola\"}'; head -c 400 /tmp/wh.json; echo"
        )
        print(f"Deploy OK — webhook: http://{host}:8447/orch/webhook/chat")

    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
