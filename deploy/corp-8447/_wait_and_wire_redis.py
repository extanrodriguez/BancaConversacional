"""Espera az login o archivo de key; luego cablea Redis QA 8447."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIGURE = Path(__file__).resolve().parent / "configure_redis_qa_8447.py"
KEY_DROP = Path(os.environ.get("REDIS_KEY_DROP", str(Path(os.environ["TEMP"]) / "azure_redis_primary.key")))
TIMEOUT_S = int(os.environ.get("WAIT_TIMEOUT_S", "600"))


def _az_cmd() -> list[str]:
    # Windows: az.cmd; Unix: az
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


def az_logged_in() -> bool:
    p = subprocess.run(
        [*_az_cmd(), "account", "show", "-o", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    if p.returncode != 0:
        return False
    try:
        json.loads(p.stdout or "{}")
        return True
    except json.JSONDecodeError:
        return False


def main() -> int:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
            os.environ["SSH_DEPLOY_PASS"] = pw
    if not pw:
        print("ERROR: SSH_DEPLOY_PASS missing")
        return 1

    print(f"Waiting up to {TIMEOUT_S}s for az login OR key file {KEY_DROP}")
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        if KEY_DROP.is_file() and KEY_DROP.stat().st_size > 8:
            key = KEY_DROP.read_text(encoding="utf-8").strip()
            os.environ["AZURE_REDIS_ACCESS_KEY"] = key
            print("KEY_SOURCE=drop_file")
            # scrub local drop file after reading into env for child
            try:
                KEY_DROP.write_text("", encoding="utf-8")
                KEY_DROP.unlink(missing_ok=True)
            except OSError:
                pass
            break
        if az_logged_in():
            print("KEY_SOURCE=az_login")
            break
        time.sleep(5)
    else:
        print("TIMEOUT waiting for key/login")
        return 2

    # run configure
    env = os.environ.copy()
    env["SSH_DEPLOY_PASS"] = pw
    p = subprocess.run([sys.executable, str(CONFIGURE)], env=env)
    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
