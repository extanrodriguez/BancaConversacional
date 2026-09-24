#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
from pathlib import Path

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")


def password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
    if not pw:
        raise SystemExit("NO_PASSWORD")
    return pw


def main() -> int:
    pw = password()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=pw, timeout=40, look_for_keys=False, allow_agent=False)
    cmd = r"""
journalctl -u genesis-cognitive-8447 -n 80 --no-pager 2>/dev/null | tail -80
echo '===='
# syntax check plan_executor
/opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python -c "from genesis_cognitive.brain.plan_executor import execute_plan; print('import_ok')"
"""
    wrapped = f"echo {shlex.quote(pw)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
    _i, stdout, stderr = c.exec_command(wrapped, timeout=90)
    print((stdout.read() + stderr.read()).decode("utf-8", "replace").replace(pw, "***")[-6000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
