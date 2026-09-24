#!/usr/bin/env python3
"""Deploy Potenciación Lunes overlay env + restart QA :8447."""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import paramiko

HOST = "20.127.25.24"
USER = "genesis"
APP = "/opt/genesis-cognitive-8447/Genesis_v2"
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
    if not pw:
        print("NO SSH_DEPLOY_PASS", file=sys.stderr)
        return 1

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=pw, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()

    def ensure_dir(remote: str) -> None:
        parts = remote.strip("/").split("/")
        cur = ""
        for p in parts:
            cur += "/" + p
            try:
                sftp.stat(cur)
            except OSError:
                try:
                    sftp.mkdir(cur)
                except OSError:
                    pass

    files = [
        "src/genesis_cognitive/rag/kb_package_ingest.py",
        "src/genesis_cognitive/context/product_catalog_aliases.py",
        "src/genesis_cognitive/router/faq_guardrail.py",
        "src/genesis_cognitive/brain/plan_interpreter.py",
        "src/genesis_cognitive/brain/plan_executor.py",
        "src/genesis_cognitive/brain/azure_plan_adapter.py",
        "src/genesis_cognitive/brain/azure_plan_turn.py",
        "src/genesis_cognitive/brain/grounded_executor.py",
        "data/kb_faq_overlay_potenciacion_lunes.json",
        "data/catalogo_campos_mapeados.json",
        "works/insumos/BSC_Potenciacion_Lunes/catalogo/productos_alias.json",
        "works/insumos/BSC_Potenciacion_Lunes/kb/chunks_qa.jsonl",
    ]
    for rel in files:
        local = ROOT / rel
        remote = f"{APP}/{rel}"
        ensure_dir(str(Path(remote).as_posix().rsplit("/", 1)[0]))
        sftp.put(str(local), remote)
        print("PUT", rel)
    sftp.close()

    remote_script = f"""
set -e
ENV={APP}/.env
touch "$ENV"
if ! grep -q '^GENESIS_FAQ_POTENCIACION_OVERLAY_PATH=' "$ENV"; then
  echo 'GENESIS_FAQ_POTENCIACION_OVERLAY_PATH={APP}/data/kb_faq_overlay_potenciacion_lunes.json' >> "$ENV"
fi
if ! grep -q '^GENESIS_KB_PACKAGE_ROOT=' "$ENV"; then
  echo 'GENESIS_KB_PACKAGE_ROOT={APP}/works/insumos/BSC_Potenciacion_Lunes' >> "$ENV"
fi
systemctl kill -s SIGKILL genesis-cognitive-8447.service 2>/dev/null || true
systemctl reset-failed genesis-cognitive-8447.service 2>/dev/null || true
systemctl start genesis-cognitive-8447.service
sleep 7
systemctl is-active genesis-cognitive-8447
curl -sS -m 8 http://127.0.0.1:8447/health
echo
grep GENESIS_FAQ_POTENCIACION_OVERLAY_PATH "$ENV"
grep GENESIS_KB_PACKAGE_ROOT "$ENV"
"""
    wrapped = f"echo {shlex.quote(pw)} | sudo -S -p '' bash -lc {shlex.quote(remote_script)}"
    _stdin, stdout, stderr = c.exec_command(wrapped, timeout=180)
    out = (stdout.read() + stderr.read()).decode("utf-8", "replace").replace(pw, "***")
    print(out)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
