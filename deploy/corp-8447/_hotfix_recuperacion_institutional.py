#!/usr/bin/env python3
"""Hotfix recuperación P0: shortcut institucional + rerank + turn allowlist."""
from __future__ import annotations

import os
import shlex
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
APP = "/opt/genesis-cognitive-8447/Genesis_v2"
RELS = [
    "src/genesis_cognitive/brain/azure_plan_adapter.py",
    "src/genesis_cognitive/brain/azure_plan_turn.py",
    "src/genesis_cognitive/rag/azure_search_retrieve.py",
]


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
    # ROOT fix: script lives in deploy/corp-8447 → parents[2] is repo
    root = Path(__file__).resolve().parents[2]
    pw = password()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=pw, timeout=40, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in RELS:
        local = root / rel
        sftp.put(str(local), f"{APP}/{rel}")
        print("PUT", rel)
    sftp.close()
    cmd = (
        "systemctl kill -s SIGKILL genesis-cognitive-8447.service 2>/dev/null || true; "
        "systemctl reset-failed genesis-cognitive-8447.service 2>/dev/null || true; "
        "systemctl start genesis-cognitive-8447.service; sleep 8; "
        "systemctl is-active genesis-cognitive-8447; "
        "curl -sS -m 8 http://127.0.0.1:8447/health; echo"
    )
    wrapped = f"echo {shlex.quote(pw)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
    _i, stdout, stderr = c.exec_command(wrapped, timeout=120)
    print((stdout.read() + stderr.read()).decode("utf-8", "replace").replace(pw, "***"))
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
