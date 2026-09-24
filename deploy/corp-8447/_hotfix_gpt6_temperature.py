#!/usr/bin/env python3
"""Hotfix temperature-safe ChatOptions files to QA :8447."""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
APP = "/opt/genesis-cognitive-8447/Genesis_v2"
RELS = [
    "src/genesis_cognitive/brain/semantic_mode.py",
    "src/genesis_cognitive/agents/agent_framework_turn_resolver.py",
    "src/genesis_cognitive/agents/semantic_verifier.py",
    "src/genesis_cognitive/router/domain_classifier.py",
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
    pw = password()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=pw, timeout=40, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in RELS:
        local = ROOT / rel
        if not local.is_file():
            raise SystemExit(f"missing {rel}")
        remote = f"{APP}/{rel}"
        sftp.put(str(local), remote)
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
