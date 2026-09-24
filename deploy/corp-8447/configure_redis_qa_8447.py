"""Obtiene Primary key de Redis Azure (si az login) y cablea QA :8447 por SSH.

Env requeridos:
  SSH_DEPLOY_PASS
Opcional:
  AZURE_REDIS_ACCESS_KEY  (si ya la tienes; no se imprime)
  SSH_HOST (default 20.127.25.24)

Si no hay AZURE_REDIS_ACCESS_KEY, intenta:
  az redisenterprise ... list-keys  /  az redis ... list-keys
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent
REMOTE_WIRE = ROOT / "_remote_wire_redis.sh"
SUB = "f2119315-95df-4c68-9f83-fb12c2ee0dfa"
RG = "RG_BSC_PRJ_GENESIS"
NAME = "bsc-cognitive-redis-qa"


def _az_cmd() -> list[str]:
    for cand in (
        os.environ.get("AZ_CLI"),
        r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
        "az",
    ):
        if not cand:
            continue
        if cand == "az" or Path(cand).exists():
            return [cand]
    return ["az"]


def _run_az(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(
        [*_az_cmd(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def fetch_primary_key() -> str | None:
    env_key = (os.environ.get("AZURE_REDIS_ACCESS_KEY") or "").strip()
    if env_key:
        print("KEY_SOURCE=env")
        return env_key

    # Managed Redis / Enterprise
    for args in (
        [
            "redisenterprise",
            "database",
            "list-keys",
            "--cluster-name",
            NAME,
            "--database-name",
            "default",
            "--resource-group",
            RG,
            "-o",
            "json",
        ],
        [
            "redis",
            "list-keys",
            "--name",
            NAME,
            "--resource-group",
            RG,
            "-o",
            "json",
        ],
    ):
        code, out = _run_az(args)
        if code != 0:
            print(f"az {' '.join(args[:3])} -> fail (no secret printed)")
            continue
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            print("az keys: invalid json")
            continue
        for k in ("primaryKey", "primaryAccessKey", "primary_key"):
            if data.get(k):
                print(f"KEY_SOURCE=az:{k}")
                return str(data[k]).strip()
        # never dump
        print("az keys: no primary field", sorted(data.keys()))
    return None


def main() -> int:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        print("ERROR: SSH_DEPLOY_PASS required")
        return 1
    key = fetch_primary_key()
    if not key:
        print("ERROR: no Redis access key (set AZURE_REDIS_ACCESS_KEY or az login + list-keys)")
        return 2

    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"SSH {user}@{host}")
    c.connect(host, username=user, password=pw, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    # upload key file then wire script
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
        tf.write(key)
        tf_path = tf.name
    try:
        sftp.put(tf_path, "/tmp/redis_primary.key")
        sftp.put(str(REMOTE_WIRE), "/tmp/_remote_wire_redis.sh")
    finally:
        Path(tf_path).unlink(missing_ok=True)
        sftp.close()

    cmd = "chmod 600 /tmp/redis_primary.key; sed -i 's/\\r$//' /tmp/_remote_wire_redis.sh; bash /tmp/_remote_wire_redis.sh"
    stdin, stdout, stderr = c.exec_command(cmd, timeout=180)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    text = out + err
    if key in text:
        text = text.replace(key, "***")
    print(text[-5000:])
    c.close()
    if code != 0 or "PING True" not in text or "DONE" not in text:
        print("FAIL wire")
        return code or 3
    print("OK redis cableado en QA 8447")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
