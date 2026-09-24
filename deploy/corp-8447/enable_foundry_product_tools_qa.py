"""Activa GENESIS_FOUNDRY_PRODUCT_TOOLS=1 en QA :8447 y reinicia el servicio.

Uso (en la misma terminal donde ya tienes la password):
  $env:SSH_DEPLOY_PASS = '...'
  $env:SSH_HOST = '20.127.25.24'
  $env:SSH_USER = 'genesis'
  .\\.venv\\Scripts\\python.exe .\\deploy\\corp-8447\\enable_foundry_product_tools_qa.py

Para desactivar: $env:FOUNDRY_PRODUCT_TOOLS_VALUE='0' y vuelve a ejecutar.
"""
from __future__ import annotations

import os
import shlex
import sys

import paramiko


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    if not password:
        print("ERROR: define SSH_DEPLOY_PASS en esta terminal")
        return 1

    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    value = os.environ.get("FOUNDRY_PRODUCT_TOOLS_VALUE", "1").strip() or "1"
    if value not in ("0", "1"):
        print("ERROR: FOUNDRY_PRODUCT_TOOLS_VALUE debe ser 0 o 1")
        return 1

    env_path = "/opt/genesis-cognitive-8447/Genesis_v2/.env"
    service = "genesis-cognitive-8447.service"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host}...")
    client.connect(
        host, username=user, password=password, timeout=30,
        look_for_keys=False, allow_agent=False,
    )
    print("SSH OK")

    def run(cmd: str, *, sudo: bool = False) -> tuple[int, str]:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=120)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        text = (out + err).strip()
        # Ocultar password si sudo la repite
        text = text.replace(password, "***")
        if text:
            print(text[-4000:])
        return code, text

    # Upsert flag en .env
    upsert = (
        f"ENV={shlex.quote(env_path)}; VAL={shlex.quote(value)}; "
        "if grep -q '^GENESIS_FOUNDRY_PRODUCT_TOOLS=' \"$ENV\"; then "
        "  sed -i \"s|^GENESIS_FOUNDRY_PRODUCT_TOOLS=.*|GENESIS_FOUNDRY_PRODUCT_TOOLS=$VAL|\" \"$ENV\"; "
        "else "
        "  echo \"GENESIS_FOUNDRY_PRODUCT_TOOLS=$VAL\" >> \"$ENV\"; "
        "fi; "
        "grep '^GENESIS_FOUNDRY_PRODUCT_TOOLS=' \"$ENV\"; "
        f"systemctl restart {service}; "
        "sleep 3; "
        f"systemctl is-active {service}; "
        "curl -sf -m 5 http://127.0.0.1:8447/ready; echo; "
        "curl -sf -m 5 http://127.0.0.1:8447/health; echo"
    )
    code, _ = run(upsert, sudo=True)
    client.close()
    if code != 0:
        print(f"FAIL exit={code}")
        return code
    print(f"OK — GENESIS_FOUNDRY_PRODUCT_TOOLS={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
