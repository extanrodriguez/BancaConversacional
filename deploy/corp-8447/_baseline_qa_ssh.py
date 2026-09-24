#!/usr/bin/env python3
"""Baseline SSH QA — no imprime secretos."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")


def password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if pw:
        return pw
    once = Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
    if once.is_file():
        return once.read_text(encoding="utf-8").strip()
    raise SystemExit("NO_PASSWORD")


def main() -> int:
    pw = password()
    print(f"pass_len={len(pw)} host={HOST} user={USER}")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=pw, timeout=30, look_for_keys=False, allow_agent=False)
    cmd = r"""
set -e
hostname
whoami
systemctl is-active genesis-cognitive-8447 || true
curl -sS -m 8 http://127.0.0.1:8447/health || true
echo
curl -sS -m 8 http://127.0.0.1:8447/ready/redis 2>/dev/null || curl -sS -m 8 http://127.0.0.1:8447/ready 2>/dev/null || echo NO_READY
echo
APP=/opt/genesis-cognitive-8447/Genesis_v2
ls -la "$APP/src/genesis_cognitive/brain/plan_executor.py" 2>/dev/null | awk '{print $5,$6,$7,$8,$9}'
test -f "$APP/src/genesis_cognitive/context/upcoming_payment_window.py" && echo HAS_P12_WINDOW || echo NO_P12_WINDOW
test -d "$APP" && echo APP_OK || echo APP_MISSING
# config keys only (no values with secrets)
grep -E '^(GENESIS_ENV|GENESIS_SEMANTIC_MODE|GENESIS_AZURE_BRAIN|GENESIS_SEARCH_RETRIEVE|GENESIS_SESSION_BACKEND|GENESIS_REDIS_|AZURE_SEARCH_INDEX|GENESIS_HOST)=' "$APP/.env" 2>/dev/null | sed 's/=.*/=***/' || true
systemctl show genesis-cognitive-8447 -p FragmentPath -p User -p WorkingDirectory -p EnvironmentFiles --no-pager 2>/dev/null | head -20
"""
    _i, stdout, stderr = c.exec_command(cmd, timeout=90)
    out = (stdout.read() + stderr.read()).decode("utf-8", "replace")
    print(out)
    c.close()
    print("SSH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
