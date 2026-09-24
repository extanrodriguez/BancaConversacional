"""Diagnóstico read-only de por qué 8446 está caído. NO modifica 8446."""
from __future__ import annotations

import os
import pathlib
import shlex
import sys

import paramiko


def main() -> int:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    once = pathlib.Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
    if not pw and once.is_file():
        pw = once.read_text(encoding="utf-8").strip()
        once.unlink(missing_ok=True)
    if not pw:
        return 1
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        os.environ.get("SSH_HOST", "20.127.25.24"),
        username=os.environ.get("SSH_USER", "genesis"),
        password=pw,
        timeout=40,
        look_for_keys=False,
        allow_agent=False,
    )
    cmd = """
echo '=== 8446 tree ==='
ls -la /opt/genesis-cognitive-8446 2>/dev/null | head -20 || echo NO_DIR
echo '=== 8446 unit ==='
systemctl status genesis-cognitive-8446.service --no-pager -l 2>&1 | head -30
echo '=== enabled ==='
systemctl is-enabled genesis-cognitive-8446.service 2>&1 || true
echo '=== journal ==='
journalctl -u genesis-cognitive-8446.service -n 40 --no-pager 2>&1 | tail -40
echo '=== env keys ==='
if [ -f /opt/genesis-cognitive-8446/Genesis_v2/.env ]; then
  grep -E '^(GENESIS_PORT|GENESIS_SEMANTIC_MODE|GENESIS_SESSION_BACKEND|GENESIS_FOUNDRY|GENESIS_AZURE|GENESIS_KB_)' /opt/genesis-cognitive-8446/Genesis_v2/.env | cut -d= -f1
else
  echo NO_ENV
fi
"""
    wrapped = f"echo {shlex.quote(pw)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
    _i, o, e = c.exec_command(wrapped, timeout=90)
    print((o.read() + e.read()).decode("utf-8", "replace").replace(pw, "***")[-6000:])
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
