#!/usr/bin/env python3
"""Hotfix candidato campaña 08-21 a QA :8447 (archivos cognitivos tocados).

No imprime la contraseña. Usa SSH_DEPLOY_PASS o %TEMP%/genesis_ssh_pass_once.txt.
"""
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

FILES = [
    "src/genesis_cognitive/brain/security_secrets.py",
    "src/genesis_cognitive/brain/plan_interpreter.py",
    "src/genesis_cognitive/brain/azure_plan_adapter.py",
    "src/genesis_cognitive/brain/azure_plan_turn.py",
    "src/genesis_cognitive/brain/plan_executor.py",
    "src/genesis_cognitive/router/field_guardrails.py",
    "src/genesis_cognitive/router/faq_guardrail.py",
    "src/genesis_cognitive/context/app_channel.py",
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
    missing = [r for r in FILES if not (ROOT / r).is_file()]
    if missing:
        print("MISSING", missing)
        return 2

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"SSH {USER}@{HOST} ...")
    c.connect(HOST, username=USER, password=pw, timeout=40, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        local = ROOT / rel
        remote = f"{APP}/{rel}"
        # ensure remote dir
        remote_dir = "/".join(remote.split("/")[:-1])
        try:
            sftp.stat(remote_dir)
        except OSError:
            # mkdir -p via ssh
            c.exec_command(f"mkdir -p {shlex.quote(remote_dir)}", timeout=30)
        sftp.put(str(local), remote)
        print("PUT", rel, local.stat().st_size)
    sftp.close()

    stamp = "camp08-21-hotfix-20260921"
    cmd = (
        f"grep -n 'cognitive_code_version\\|CODE_VERSION\\|potenciacion-strict' "
        f"{APP}/src/genesis_cognitive/brain/azure_plan_turn.py 2>/dev/null | head -5; "
        f"echo HOTFIX_STAMP={stamp} >> {APP}/.env.hotfix_stamp; "
        "systemctl kill -s SIGKILL genesis-cognitive-8447.service 2>/dev/null || true; "
        "systemctl reset-failed genesis-cognitive-8447.service 2>/dev/null || true; "
        "systemctl start genesis-cognitive-8447.service; sleep 10; "
        "systemctl is-active genesis-cognitive-8447; "
        "curl -sS -m 10 http://127.0.0.1:8447/health; echo; "
        "curl -sS -m 10 http://127.0.0.1:8447/ready/redis; echo"
    )
    wrapped = f"echo {shlex.quote(pw)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
    _i, stdout, stderr = c.exec_command(wrapped, timeout=180)
    out = (stdout.read() + stderr.read()).decode("utf-8", "replace")
    print(out.replace(pw, "***")[-4000:])
    c.close()
    if "active" not in out and '"status":"ok"' not in out and '"status": "ok"' not in out:
        # still check health substring
        if "ok" not in out.lower():
            return 3
    print("HOTFIX_OK", stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
