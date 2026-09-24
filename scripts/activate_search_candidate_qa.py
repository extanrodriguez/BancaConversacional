#!/usr/bin/env python3
"""Activa AZURE_SEARCH_INDEX=candidato en QA :8447 sin tocar secretos."""
from __future__ import annotations

import json
import os
import shlex
import time
from pathlib import Path

import httpx
import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
APP = "/opt/genesis-cognitive-8447/Genesis_v2"
ENV = f"{APP}/.env"
CAND = "bsc-kb-qa-vnext-20260921"
PREV = "bsc-kb-conocimiento"
EVID = Path("works/azure_mejora/search_candidate_20260921")


def password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        pw = once.read_text(encoding="utf-8").strip()
    if not pw:
        raise SystemExit("NO SSH_DEPLOY_PASS")
    return pw


def run(client: paramiko.SSHClient, cmd: str, *, sudo: bool, pw: str, timeout: int = 180) -> tuple[int, str]:
    wrapped = f"sudo -S -p '' bash -lc {shlex.quote(cmd)}" if sudo else cmd
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=timeout)
    if sudo:
        stdin.write(pw + "\n")
        stdin.flush()
    out = (stdout.read() + stderr.read()).decode("utf-8", "replace").replace(pw, "***")
    return stdout.channel.recv_exit_status(), out


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    pw = password()
    ts = str(int(time.time()))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=pw, timeout=40, look_for_keys=False, allow_agent=False)
    print("SSH_OK")

    code, before = run(client, f"grep -E '^AZURE_SEARCH_INDEX=' {ENV} || true", sudo=True, pw=pw)
    print("BEFORE", before.strip())

    remote = f"""
set -euo pipefail
test -f '{ENV}'
cp -a '{ENV}' '{APP}/.env.bak_search_{ts}'
if grep -q '^AZURE_SEARCH_INDEX=' '{ENV}'; then
  sed -i 's/^AZURE_SEARCH_INDEX=.*/AZURE_SEARCH_INDEX={CAND}/' '{ENV}'
else
  printf '\\nAZURE_SEARCH_INDEX={CAND}\\n' >> '{ENV}'
fi
grep -E '^AZURE_SEARCH_INDEX=' '{ENV}'
systemctl restart genesis-cognitive-8447
sleep 6
systemctl is-active genesis-cognitive-8447
"""
    code, out = run(client, remote, sudo=True, pw=pw, timeout=180)
    print(out)
    print("activate_code", code)
    if code != 0:
        client.close()
        return code

    code2, after = run(client, f"grep -E '^AZURE_SEARCH_INDEX=' {ENV}", sudo=True, pw=pw)
    print("AFTER", after.strip())
    client.close()

    # smoke
    for _ in range(10):
        try:
            h = httpx.get(f"http://{HOST}:8447/health", timeout=10)
            if h.status_code == 200:
                print("health", h.text[:120])
                break
        except Exception as exc:  # noqa: BLE001
            print("wait", type(exc).__name__)
        time.sleep(2)

    ready = httpx.get(f"http://{HOST}:8447/ready/redis", timeout=15)
    print("ready", ready.status_code, ready.text[:200])

    turn = httpx.post(
        f"http://{HOST}:8447/turn",
        json={
            "question": "compara visa platinum e infinite",
            "conversation_id": f"cand-act-{ts}",
            "client_id": "726588",
        },
        timeout=90,
    )
    data = turn.json() if turn.headers.get("content-type", "").startswith("application/json") else {}
    reply = str(data.get("reply") or data.get("answer") or "")
    print("turn", turn.status_code)
    print("reply_prefix", reply[:400])

    payload = {
        "candidate": CAND,
        "previous": PREV,
        "activated": True,
        "env_after": after.strip(),
        "turn_http": turn.status_code,
        "reply_prefix": reply[:600],
        "utc": ts,
        "rollback": f"AZURE_SEARCH_INDEX={PREV}; systemctl restart genesis-cognitive-8447",
    }
    (EVID / "activation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("evidence", EVID / "activation.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
