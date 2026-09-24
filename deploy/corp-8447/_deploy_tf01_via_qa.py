"""Deploy cierre V4 cognitive patches to vm-genesis-bc-tf-01 via QA jump host."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
BASE = "/opt/genesis-cognitive-8447/Genesis_v2"
FILES = [
    "src/genesis_cognitive/brain/azure_plan_turn.py",
    "src/genesis_cognitive/brain/azure_plan_adapter.py",
    "src/genesis_cognitive/brain/plan_interpreter.py",
    "src/genesis_cognitive/brain/plan_executor.py",
    "src/genesis_cognitive/context/app_channel.py",
    "src/genesis_cognitive/demo/contract_inspector_app.py",
    "src/genesis_cognitive/context/redis_client_factory.py",
    "src/genesis_cognitive/context/conversation_gate.py",
    "src/genesis_cognitive/context/redis_session_store.py",
    "src/genesis_cognitive/brain/semantic_mode.py",
]


def main() -> int:
    pw_qa = os.environ["SSH_DEPLOY_PASS"].strip()
    pw_tf = os.environ.get("TF_DEPLOY_PASS", "").strip()
    if not pw_tf:
        print("ERROR: TF_DEPLOY_PASS unset")
        return 1

    jump = paramiko.SSHClient()
    jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    jump.connect(
        "20.127.25.24",
        username="genesis",
        password=pw_qa,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    chan = jump.get_transport().open_channel(
        "direct-tcpip", ("192.168.150.6", 22), ("127.0.0.1", 0)
    )
    tf = paramiko.SSHClient()
    tf.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    tf.connect(
        "192.168.150.6",
        username="genesis",
        password=pw_tf,
        sock=chan,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    sftp_qa = jump.open_sftp()
    sftp_tf = tf.open_sftp()

    def sudo(cmd: str, timeout: int = 180) -> str:
        wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
        stdin, stdout, stderr = tf.exec_command(wrapped, get_pty=True, timeout=timeout)
        stdin.write(pw_tf + "\n")
        stdin.flush()
        return (stdout.read() + stderr.read()).decode("utf-8", "replace")

    print("TF", sudo("hostname; systemctl is-active genesis-cognitive-8447").strip())
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak_dir = f"/tmp/cierre_v4_bak_{ts}"
    sudo(f"mkdir -p {bak_dir}")

    uploaded: list[str] = []
    for rel in FILES:
        local = ROOT / rel
        remote = f"{BASE}/{rel}"
        if local.is_file():
            data = local.read_bytes()
            src = "local"
        else:
            try:
                with sftp_qa.open(f"{BASE}/{rel}", "rb") as fh:
                    data = fh.read()
                src = "qa"
            except Exception as exc:  # noqa: BLE001
                print("SKIP", rel, type(exc).__name__)
                continue
        bak_name = rel.replace("/", "_")
        sudo(f"cp -a {shlex.quote(remote)} {shlex.quote(bak_dir + '/' + bak_name)} 2>/dev/null || true")
        tmp = f"/tmp/deploy_{hashlib.sha256(rel.encode()).hexdigest()[:12]}.bin"
        with sftp_tf.open(tmp, "wb") as fh:
            fh.write(data)
        out = sudo(
            f"cp -a {shlex.quote(tmp)} {shlex.quote(remote)} && "
            f"sed -i 's/\\r$//' {shlex.quote(remote)} && "
            f"sha256sum {shlex.quote(remote)}"
        )
        dig = hashlib.sha256(data).hexdigest()[:16]
        last = [ln for ln in out.splitlines() if ln.strip()][-1] if out.strip() else ""
        print("UP", src, dig, rel)
        print(" ", last.encode("ascii", "replace").decode("ascii"))
        uploaded.append(rel)

    print("UPLOADED", len(uploaded), "BAK", bak_dir)
    restart = sudo(
        "systemctl kill -s SIGKILL genesis-cognitive-8447.service 2>/dev/null || true; "
        "systemctl reset-failed genesis-cognitive-8447.service 2>/dev/null || true; "
        "systemctl start genesis-cognitive-8447.service; sleep 5; "
        "systemctl is-active genesis-cognitive-8447; "
        "curl -sS -m 8 http://127.0.0.1:8447/health; echo; "
        "curl -sS -m 12 http://127.0.0.1:8447/ready/redis | head -c 220; echo"
    )
    print(restart[-2000:].encode("ascii", "replace").decode("ascii"))

    conv = f"smoke-port-{int(time.time())}"
    smoke_py = (
        "import sys,json,re\n"
        "d=json.loads(sys.stdin.read())\n"
        "a=d.get('app_channel') or {}\n"
        "print('SMOKE', a.get('status') or d.get('status'), a.get('intent_id') or d.get('intent_id'))\n"
        "print(re.sub(r'\\b\\d{4,}\\b','####', (a.get('client_response') or '')[:240]))\n"
    )
    smoke = sudo(
        f"curl -sS -m 30 -X POST http://127.0.0.1:8447/orch/context "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"customer_id\":\"726588\",\"conversation_id\":\"{conv}\",\"allow_lab_fallback\":true}}' "
        f"| head -c 200; echo; "
        f"curl -sS -m 120 -X POST http://127.0.0.1:8447/turn "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"conversation_id\":\"{conv}\",\"customer_id\":\"726588\",\"question\":\"listame mis productos\"}}' "
        f"| {BASE}/.venv/bin/python -c {shlex.quote(smoke_py)}"
    )
    print(smoke[-1800:].encode("ascii", "replace").decode("ascii"))

    sftp_tf.close()
    sftp_qa.close()
    tf.close()
    jump.close()
    print(json.dumps({"ok": True, "uploaded": len(uploaded), "bak": bak_dir}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
