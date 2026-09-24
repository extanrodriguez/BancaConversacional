"""Hotfix QA 8447 — typos misión/visión → KB (no portafolio)."""
from __future__ import annotations

import json
import os
import pathlib
import shlex
import time
import urllib.request

import paramiko

LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
REMOTE_LAB = "/opt/genesis-cognitive-8447/lab8446_runtime"
REL = "lab8446/semantic_intent.py"


def _password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        raise SystemExit("ERROR: SSH_DEPLOY_PASS")
    return pw


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    local = LAB / REL
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=40, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    tmp = f"/tmp/hotfix_mision_{int(time.time())}.py"
    sftp.put(str(local), tmp)
    sftp.close()

    def run_sudo(cmd: str) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _i, stdout, stderr = client.exec_command(wrapped, timeout=120)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")
        return stdout.channel.recv_exit_status(), out

    code, out = run_sudo(
        f"cp -f {shlex.quote(tmp)} {REMOTE_LAB}/{REL} && chown genesis:genesis {REMOTE_LAB}/{REL} && "
        "systemctl restart genesis-cognitive-8447.service; sleep 5; "
        "systemctl is-active genesis-cognitive-8447.service; "
        f"rm -f {shlex.quote(tmp)}"
    )
    print(out[-2000:])
    if code != 0:
        client.close()
        return code

    # smoke from local against public QA
    body = {
        "conversation_id": "smoke-mision",
        "question": "cual es la misiin del banco",
        "customer_id": "726588",
        "debug": True,
    }
    req = urllib.request.Request(
        "http://20.127.25.24:8447/turn",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode())
    reply = data.get("reply") or ""
    dbg = data.get("debug") or {}
    print("MODE", dbg.get("mode"))
    print("INTENT", dbg.get("intent"))
    print("REPLY", reply[:350].encode("ascii", "replace").decode("ascii"))
    print("OK_MISION", "misi" in reply.lower() or "emprendedor" in reply.lower())
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
