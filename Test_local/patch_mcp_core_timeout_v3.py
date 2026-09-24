"""Bajar timeout de TODAS las llamadas Core ops en MCP (no solo el bloque final)."""
from __future__ import annotations

import os
import shlex
import tempfile
from pathlib import Path

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
PASSWORD = os.environ["SSH_DEPLOY_PASS"]
REMOTE = "/opt/genesis/mcp-bridge/main.py"
MARKER = "_mcp_core_ops_timeout_wrap_v3"


def sudo(c, cmd: str) -> tuple[int, str]:
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = c.exec_command(wrapped, get_pty=True, timeout=90)
    stdin.write(PASSWORD + "\n")
    stdin.flush()
    out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out


WRAP = r'''
# _mcp_core_ops_timeout_wrap_v3
def call_json(method: str, url: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 45) -> Dict[str, Any]:
    if url and ("core/v1/operations" in url.lower() or url.rstrip("/").endswith("/operations")):
        timeout = int(os.getenv("CORE_OPS_TIMEOUT", "5"))
    return _call_json_core_timeout_orig(method, url, payload, timeout=timeout)

'''


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="genesis", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    with sftp.open(REMOTE, "r") as f:
        text = f.read().decode("utf-8", errors="replace")

    if MARKER in text:
        print("timeout wrap already present")
    else:
        # Rename original call_json once (first definition only)
        old = "def call_json(method: str, url: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 45) -> Dict[str, Any]:"
        if old not in text:
            print("ERROR: call_json def not found")
            return 1
        text = text.replace(old, "def _call_json_core_timeout_orig(method: str, url: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 45) -> Dict[str, Any]:", 1)
        # Insert wrapper after original function ends — before extract_raw_text or before cognitive helpers
        anchor = "\ndef extract_raw_text(payload: Dict[str, Any]) -> str:"
        # Prefer insert before CORE_OPS_TIMEOUT helper block if present
        if "\n# _mcp_skip_core_when_cognitive_answered_v2" in text:
            anchor = "\n# _mcp_skip_core_when_cognitive_answered_v2"
        if anchor not in text:
            print("ERROR: insert anchor missing")
            return 1
        text = text.replace(anchor, "\n" + WRAP + anchor, 1)

        local = Path(tempfile.gettempdir()) / "mcp_timeout_v3.py"
        local.write_text(text, encoding="utf-8", newline="\n")
        sftp.put(str(local), "/tmp/mcp_timeout_v3.py")
        code, out = sudo(c, f"cp /tmp/mcp_timeout_v3.py {REMOTE} && python3 -m py_compile {REMOTE} && systemctl restart genesis-mcp-bridge && sleep 2 && systemctl is-active genesis-mcp-bridge")
        print(out[-1500:])
        if code != 0:
            return 1
        print("patched")

    sftp.close()
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
