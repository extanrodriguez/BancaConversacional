"""Deploy portfolio-aware tasa/alias a QA + tf-01 y smoke vía /lab/login."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
BASE = "/opt/genesis-cognitive-8447/Genesis_v2"
FILES = [
    "src/genesis_cognitive/brain/plan_interpreter.py",
    "src/genesis_cognitive/brain/plan_executor.py",
    "src/genesis_cognitive/brain/azure_plan_adapter.py",
    "src/genesis_cognitive/context/app_channel.py",
    "src/genesis_cognitive/context/core_portfolio_mapper.py",
    "data/lab_portfolios/qa_726588_contract_demo.json",
    "data/lab_usuarios.json",
]
QUESTIONS = [
    "cual es mi tasa de interes",
    "cual es el saldo de mi tarjeta joven",
    "cual es la tasa de mi tarjeta joven",
]


def _upload(sftp, sudo_fn, rel: str, data: bytes) -> None:
    remote = f"{BASE}/{rel}"
    tmp = f"/tmp/pf_{hashlib.sha256(rel.encode()).hexdigest()[:10]}.bin"
    with sftp.open(tmp, "wb") as fh:
        fh.write(data)
    parent = str(Path(remote).parent).replace("\\", "/")
    sudo_fn(
        f"mkdir -p {shlex.quote(parent)} && "
        f"cp -a {shlex.quote(tmp)} {shlex.quote(remote)} && "
        f"sed -i 's/\\r$//' {shlex.quote(remote)}"
    )
    print("UP", rel, hashlib.sha256(data).hexdigest()[:12])


def _smoke(sudo_fn, label: str) -> None:
    stamp = int(time.time())
    for i, q in enumerate(QUESTIONS):
        conv = f"labrate-{stamp}-{i}"
        py = (
            "import sys,json,re\n"
            "d=json.loads(sys.stdin.read()); a=d.get('app_channel') or {}\n"
            "opts=a.get('options') or []\n"
            "print(a.get('status') or d.get('status'), a.get('intent_id') or d.get('intent_id'), 'opts', len(opts))\n"
            "print(re.sub(r'\\b\\d{4,}\\b','####', (a.get('client_response') or '')[:280]))\n"
            "for o in opts[:8]:\n"
            "  print(' -', o.get('ref') or o.get('option_ref') or o.get('id'), '|', (o.get('label') or o.get('text') or '')[:90])\n"
        )
        login = (
            f"curl -sS -m 30 -X POST http://127.0.0.1:8447/lab/login "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"customer_id\":\"726588\",\"conversation_id\":\"{conv}\","
            f"\"portfolio\":\"qa_726588_contract_demo.json\"}}' >/dev/null"
        )
        turn = (
            f"curl -sS -m 180 -X POST http://127.0.0.1:8447/turn "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"conversation_id\":\"{conv}\",\"customer_id\":\"726588\","
            f"\"question\":{json.dumps(q)}}}' "
            f"| {BASE}/.venv/bin/python -c {shlex.quote(py)}"
        )
        print(f"--- {label} Q: {q} ---")
        out = sudo_fn(f"{login}; {turn}", timeout=240)
        lines = [
            ln for ln in out.splitlines()
            if not ln.startswith("[sudo]") and "password" not in ln.lower()
        ]
        print("\n".join(lines[-20:]).encode("ascii", "replace").decode("ascii"))


def _host(client, password, label: str, payloads: dict[str, bytes]) -> None:
    sftp = client.open_sftp()

    def sudo(cmd: str, timeout: int = 120) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
        stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=timeout)
        stdin.write(password + "\n")
        stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", "replace")

    print("===", label, "===")
    for rel, data in payloads.items():
        _upload(sftp, sudo, rel, data)
    print(
        sudo(
            "systemctl restart genesis-cognitive-8447; sleep 5; "
            "systemctl is-active genesis-cognitive-8447"
        ).strip().splitlines()[-1]
    )
    _smoke(sudo, label)
    sftp.close()


def main() -> int:
    pw_qa = os.environ["SSH_DEPLOY_PASS"].strip()
    pw_tf = os.environ["TF_DEPLOY_PASS"].strip()
    payloads = {rel: (ROOT / rel).read_bytes() for rel in FILES}

    qa = paramiko.SSHClient()
    qa.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    qa.connect(
        "20.127.25.24", username="genesis", password=pw_qa,
        timeout=30, look_for_keys=False, allow_agent=False,
    )
    _host(qa, pw_qa, "QA", payloads)

    chan = qa.get_transport().open_channel(
        "direct-tcpip", ("192.168.150.6", 22), ("127.0.0.1", 0)
    )
    tf = paramiko.SSHClient()
    tf.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    tf.connect(
        "192.168.150.6", username="genesis", password=pw_tf, sock=chan,
        timeout=30, look_for_keys=False, allow_agent=False,
    )
    _host(tf, pw_tf, "TF-01", payloads)
    tf.close()
    qa.close()
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
