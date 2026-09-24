"""Parche subject_token = customer_id en mcp-bridge."""
from __future__ import annotations

import os
import shlex

import paramiko

PATCH = r'''
from pathlib import Path
import time
p = Path("/opt/genesis/mcp-bridge/main.py")
text = p.read_text(encoding="utf-8")
old = (
    "def get_subject_token(payload: Dict[str, Any]) -> str:\n"
    "    return payload.get(\"subject_token\") or payload.get(\"subjectToken\") or \"cust_core_001\""
)
new = (
    "def get_subject_token(payload: Dict[str, Any]) -> str:\n"
    "    return (\n"
    "        payload.get(\"subject_token\")\n"
    "        or payload.get(\"subjectToken\")\n"
    "        or payload.get(\"customer_id\")\n"
    "        or payload.get(\"customerId\")\n"
    "        or payload.get(\"client_id\")\n"
    "        or payload.get(\"clientId\")\n"
    "        or \"cust_core_001\"\n"
    "    )"
)
if "or payload.get(\"customer_id\")" in text[text.find("def get_subject_token"): text.find("def get_subject_token")+500]:
    print("subject_token already patched")
elif old not in text:
    raise SystemExit("get_subject_token not found")
else:
    stamp = time.strftime("%Y%m%d%H%M%S")
    Path(f"/opt/genesis/mcp-bridge/main.py.bak.subject.{stamp}").write_text(text, encoding="utf-8")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("patched get_subject_token")
'''


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        os.environ.get("SSH_HOST", "20.127.25.24"),
        username=os.environ.get("SSH_USER", "genesis"),
        password=password,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )

    def run(cmd: str, *, sudo: bool = False) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=180)
        if sudo:
            stdin.write(password + "\n")
            stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

    sftp = client.open_sftp()
    with sftp.file("/tmp/patch_mcp_subject.py", "w") as f:
        f.write(PATCH)
    sftp.close()
    print(run("python3 /tmp/patch_mcp_subject.py", sudo=True))
    print(run("systemctl restart genesis-mcp-bridge && sleep 2 && systemctl is-active genesis-mcp-bridge", sudo=True))

    # Load context first like Context Refresh, then chat via orch
    print("=== login context ===")
    print(
        run(
            "curl -sS -m 20 -X POST http://127.0.0.1:8447/lab/login "
            "-H 'Content-Type: application/json' "
            "-d '{\"customer_id\":\"TEST-QA-001\",\"conversation_id\":\"sim-orch-4\",\"portfolio\":\"qa_andres_david.json\"}'"
        )
    )
    print("=== orch chat ===")
    print(
        run(
            "curl -sS -m 40 -X POST http://127.0.0.1:8080/chat/front "
            "-H 'Content-Type: application/json' "
            "-d '{\"question\":\"hola\",\"customer_id\":\"TEST-QA-001\",\"client_id\":\"TEST-QA-001\",\"subject_token\":\"TEST-QA-001\",\"conversation_id\":\"sim-orch-4\"}' "
            "| head -c 900; echo"
        )
    )
    print("=== balance ===")
    print(
        run(
            "curl -sS -m 40 -X POST http://127.0.0.1:8080/chat/front "
            "-H 'Content-Type: application/json' "
            "-d '{\"question\":\"dame un balance de mis cuentas\",\"customer_id\":\"TEST-QA-001\",\"client_id\":\"TEST-QA-001\",\"subject_token\":\"TEST-QA-001\",\"conversation_id\":\"sim-orch-4\"}' "
            "| head -c 900; echo"
        )
    )
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
