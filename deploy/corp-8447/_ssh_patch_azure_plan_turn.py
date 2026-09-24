"""Upload azure_plan_turn.py and restart 8447."""
from __future__ import annotations

import os
import pathlib
import shlex
import sys

import paramiko


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    if not password:
        print("ERROR: SSH_DEPLOY_PASS")
        return 1
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    local = pathlib.Path(__file__).resolve().parents[2] / "src/genesis_cognitive/brain/azure_plan_turn.py"
    remote = "/opt/genesis-cognitive-8447/Genesis_v2/src/genesis_cognitive/brain/azure_plan_turn.py"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    sftp.put(str(local), remote)
    sftp.close()
    print("UPLOADED azure_plan_turn.py")

    def run(cmd: str) -> None:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=120)
        stdin.write(password + "\n")
        stdin.flush()
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
        print(out[-2000:].encode("ascii", "replace").decode("ascii"))

    run(
        f"sed -i 's/\\r$//' {shlex.quote(remote)}; "
        "sudo systemctl kill -s SIGKILL genesis-cognitive-8447.service 2>/dev/null || true; "
        "sudo systemctl reset-failed genesis-cognitive-8447.service 2>/dev/null || true; "
        "sudo systemctl start genesis-cognitive-8447.service; sleep 5; "
        "systemctl is-active genesis-cognitive-8447; "
        "curl -sS -m 8 http://127.0.0.1:8447/health; echo; "
        "curl -sS -m 10 http://127.0.0.1:8447/ready/redis; echo"
    )
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
