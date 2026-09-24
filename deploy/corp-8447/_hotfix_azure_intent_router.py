"""Hotfix: Azure tool_choice decide portafolio vs KB."""
from __future__ import annotations

import json
import os
import pathlib
import shlex
import time
import urllib.request

import paramiko

LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
REMOTE = "/opt/genesis-cognitive-8447/lab8446_runtime"
FILES = ["lab8446/agent.py", "lab8446/tools.py", "lab8446/semantic_intent.py"]


def main() -> int:
    password = os.environ["SSH_DEPLOY_PASS"].strip()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        "20.127.25.24", username="genesis", password=password,
        timeout=40, look_for_keys=False, allow_agent=False,
    )
    sftp = client.open_sftp()
    ts = int(time.time())
    pairs = []
    for rel in FILES:
        tmp = f"/tmp/hotfix_azure_router_{pathlib.Path(rel).name}_{ts}"
        sftp.put(str(LAB / rel), tmp)
        pairs.append((tmp, f"{REMOTE}/{rel}"))
        print("PUT", rel)
    sftp.close()
    copies = " && ".join(
        f"cp -f {shlex.quote(s)} {shlex.quote(d)} && chown genesis:genesis {shlex.quote(d)}"
        for s, d in pairs
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(s)}" for s, _ in pairs)
    cmd = (
        f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc "
        + shlex.quote(
            f"{copies} && systemctl restart genesis-cognitive-8447.service; sleep 6; "
            f"systemctl is-active genesis-cognitive-8447.service; {cleanup}"
        )
    )
    _i, stdout, stderr = client.exec_command(cmd, timeout=120)
    print((stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")[-800:])
    client.close()

    for q in [
        "cual es la misiin del banco",
        "lista mis productos",
        "hablame de la visa platinum",
    ]:
        body = {
            "conversation_id": f"smoke-az-{abs(hash(q)) % 99999}",
            "question": q,
            "customer_id": "726588",
            "debug": True,
        }
        req = urllib.request.Request(
            "http://20.127.25.24:8447/turn",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        dbg = data.get("debug") or {}
        print(
            "Q:", q,
            "| router:", dbg.get("router"),
            "| chose:", dbg.get("azure_chose_tools"),
            "| tools:", [(t.get("name"), t.get("result_status")) for t in (dbg.get("tool_calls") or [])],
            "| reply:", (data.get("reply") or "")[:100].encode("ascii", "replace").decode("ascii"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
