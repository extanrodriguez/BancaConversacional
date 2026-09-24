"""Upload tasa-fix files to QA (20.127.25.24) and tf-01 (192.168.150.6 via jump)."""
from __future__ import annotations

import hashlib
import os
import shlex
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
BASE = "/opt/genesis-cognitive-8447/Genesis_v2"
FILES = [
    "src/genesis_cognitive/brain/plan_interpreter.py",
    "src/genesis_cognitive/brain/azure_plan_adapter.py",
]


def _upload(sftp, sudo_fn, rel: str, data: bytes) -> None:
    remote = f"{BASE}/{rel}"
    tmp = f"/tmp/tasa_{hashlib.sha256(rel.encode()).hexdigest()[:10]}.bin"
    with sftp.open(tmp, "wb") as fh:
        fh.write(data)
    sudo_fn(
        f"cp -a {shlex.quote(tmp)} {shlex.quote(remote)} && "
        f"sed -i 's/\\r$//' {shlex.quote(remote)}"
    )
    print("UP", rel, hashlib.sha256(data).hexdigest()[:16])


def main() -> int:
    pw_qa = os.environ["SSH_DEPLOY_PASS"].strip()
    pw_tf = os.environ.get("TF_DEPLOY_PASS", "").strip()
    payloads = {rel: (ROOT / rel).read_bytes() for rel in FILES}

    # --- QA ---
    qa = paramiko.SSHClient()
    qa.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    qa.connect("20.127.25.24", username="genesis", password=pw_qa, timeout=30,
               look_for_keys=False, allow_agent=False)
    sftp_qa = qa.open_sftp()

    def sudo_qa(cmd: str) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
        stdin, stdout, stderr = qa.exec_command(wrapped, get_pty=True, timeout=120)
        stdin.write(pw_qa + "\n"); stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", "replace")

    print("=== QA ===")
    for rel, data in payloads.items():
        _upload(sftp_qa, sudo_qa, rel, data)
    print(sudo_qa(
        "systemctl restart genesis-cognitive-8447; sleep 4; "
        "systemctl is-active genesis-cognitive-8447"
    ).strip().splitlines()[-1])

    # smoke QA
    conv = f"tasa-{int(time.time())}"
    smoke = (
        "import sys,json,re\n"
        "d=json.loads(sys.stdin.read()); a=d.get('app_channel') or {}\n"
        "print(a.get('status') or d.get('status'), a.get('intent_id') or d.get('intent_id'))\n"
        "print(re.sub(r'\\b\\d{4,}\\b','####', (a.get('client_response') or '')[:160]))\n"
    )
    out = sudo_qa(
        f"curl -sS -m 30 -X POST http://127.0.0.1:8447/orch/context -H 'Content-Type: application/json' "
        f"-d '{{\"customer_id\":\"726588\",\"conversation_id\":\"{conv}\",\"allow_lab_fallback\":true}}' >/dev/null; "
        f"curl -sS -m 120 -X POST http://127.0.0.1:8447/turn -H 'Content-Type: application/json' "
        f"-d '{{\"conversation_id\":\"{conv}\",\"customer_id\":\"726588\",\"question\":\"cuál es mi tasa de interés\"}}' "
        f"| {BASE}/.venv/bin/python -c {shlex.quote(smoke)}"
    )
    print(out[-500:].encode("ascii", "replace").decode("ascii"))
    sftp_qa.close()

    if pw_tf:
        print("=== TF-01 ===")
        chan = qa.get_transport().open_channel(
            "direct-tcpip", ("192.168.150.6", 22), ("127.0.0.1", 0)
        )
        tf = paramiko.SSHClient()
        tf.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        tf.connect("192.168.150.6", username="genesis", password=pw_tf, sock=chan,
                   timeout=30, look_for_keys=False, allow_agent=False)
        sftp_tf = tf.open_sftp()

        def sudo_tf(cmd: str) -> str:
            wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
            stdin, stdout, stderr = tf.exec_command(wrapped, get_pty=True, timeout=120)
            stdin.write(pw_tf + "\n"); stdin.flush()
            return (stdout.read() + stderr.read()).decode("utf-8", "replace")

        for rel, data in payloads.items():
            _upload(sftp_tf, sudo_tf, rel, data)
        print(sudo_tf(
            "systemctl restart genesis-cognitive-8447; sleep 4; "
            "systemctl is-active genesis-cognitive-8447"
        ).strip().splitlines()[-1])
        sftp_tf.close(); tf.close()

    qa.close()
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
