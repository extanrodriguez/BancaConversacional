"""Upload patched contract_inspector_app.py and restart 8447 (SSH password)."""
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
    local = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src"
        / "genesis_cognitive"
        / "demo"
        / "contract_inspector_app.py"
    )
    remote = "/opt/genesis-cognitive-8447/Genesis_v2/src/genesis_cognitive/demo/contract_inspector_app.py"
    if not local.is_file():
        print(f"ERROR missing {local}")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    # backup then put
    bak = remote + f".bak.asyncfix.{os.environ.get('TS', 'now')}"
    try:
        sftp.get(remote, str(local.parent / "_remote_bak_contract_inspector_app.py"))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN backup pull: {type(exc).__name__}")
    sftp.put(str(local), remote)
    sftp.close()
    print(f"UPLOADED {local.name} -> {remote}")

    def run(cmd: str, *, sudo: bool = False) -> int:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        try:
            print(out[-4000:])
        except UnicodeEncodeError:
            print(out[-4000:].encode("ascii", "replace").decode("ascii"))
        return code

    # strip CR if any, restart with kill if needed
    run(f"sed -i 's/\\r$//' {shlex.quote(remote)}", sudo=True)
    run(
        "sudo systemctl kill -s SIGKILL genesis-cognitive-8447.service 2>/dev/null || true; "
        "sudo systemctl reset-failed genesis-cognitive-8447.service 2>/dev/null || true; "
        "sudo systemctl start genesis-cognitive-8447.service; "
        "sleep 5; "
        "systemctl is-active genesis-cognitive-8447; "
        "curl -sS -m 5 http://127.0.0.1:8447/health; echo; "
        "curl -sS -m 12 -w '\\nHTTP:%{http_code} T:%{time_total}\\n' http://127.0.0.1:8447/ready/redis",
        sudo=True,
    )
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
