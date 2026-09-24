"""Probar servicio Core/context api-genesis desde la VM."""
from __future__ import annotations

import os
import shlex

import paramiko


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        os.environ.get("SSH_HOST", "20.127.25.24"),
        username=os.environ.get("SSH_USER", "genesis"),
        password=password,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )

    def run(cmd: str, *, sudo: bool = False) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=90)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

    print("=== grep urls ===")
    print(
        run(
            "grep -RInE 'api-genesis|bsc.com.do|/ws/\\?customerId|customerId=' "
            "/opt/genesis /opt/genesis-rag /opt/genesis-cognitive-8447/Genesis_v2 "
            "--include='*.py' --include='*.env' --include='*.md' --include='*.json' "
            "--include='*.js' --include='*.ts' 2>/dev/null | head -80"
        )
    )
    print("=== curl ws ===")
    print(
        run(
            "curl -sS -m 20 -D - "
            "'https://api-genesis.dev.bsc.com.do/ws/?customerId=726588' "
            "-o /tmp/ws_out.json; echo; head -c 1200 /tmp/ws_out.json; echo"
        )
    )
    print("=== curl variants ===")
    for u in [
        "https://api-genesis.dev.bsc.com.do/ws/?customerId=726588",
        "https://api-genesis.dev.bsc.com.do/ws/context?customerId=726588",
        "https://api-genesis.dev.bsc.com.do/api/ws/?customerId=726588",
        "http://4.227.182.177:8090/core/health",
    ]:
        print(
            run(
                f"echo 'URL={u}'; curl -sS -m 12 -o /tmp/u.out -w 'code=%{{http_code}} bytes=%{{size_download}}\\n' '{u}'; head -c 200 /tmp/u.out; echo"
            )
        )
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
