"""SFTP a remote script and execute; print stdout. Env: SSH_DEPLOY_PASS, REMOTE_SCRIPT, REMOTE_NAME."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko


def main() -> int:
    pw = os.environ["SSH_DEPLOY_PASS"].strip()
    local = Path(os.environ["REMOTE_SCRIPT"])
    remote = os.environ.get("REMOTE_NAME", f"/tmp/{local.name}")
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    use_sudo = os.environ.get("REMOTE_SUDO", "0") == "1"

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=pw, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    sftp.put(str(local), remote)
    sftp.close()

    cmd = f"sed -i 's/\\r$//' {remote} && bash {remote}"
    if use_sudo:
        stdin, stdout, stderr = c.exec_command(f"sudo -S bash -lc {cmd!r}", get_pty=True, timeout=180)
        stdin.write(pw + "\n")
        stdin.flush()
    else:
        stdin, stdout, stderr = c.exec_command(cmd, timeout=180)

    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    sys.stdout.write(out)
    if err:
        sys.stdout.write(err)
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
