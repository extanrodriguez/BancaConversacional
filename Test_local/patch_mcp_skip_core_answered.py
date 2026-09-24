"""Patch MCP bridge: no colgar en saldo cuando cognitiva ya respondió."""
from __future__ import annotations

import os
import shlex
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
PASSWORD = os.environ.get("SSH_DEPLOY_PASS")
REMOTE = "/opt/genesis/mcp-bridge/main.py"
MARKER = "_mcp_skip_core_when_cognitive_answered_v1"

if not PASSWORD:
    print("ERROR: SSH_DEPLOY_PASS missing")
    sys.exit(1)

HELPER = r'''
# _mcp_skip_core_when_cognitive_answered_v1
CORE_OPS_TIMEOUT = int(os.getenv("CORE_OPS_TIMEOUT", "5"))


def _is_core_operations_url(url: str) -> bool:
    u = (url or "").lower()
    return "core/v1/operations" in u or u.rstrip("/").endswith("/operations")


_call_json_orig = call_json


def call_json(method: str, url: str, payload=None, timeout: int = 45):
    if _is_core_operations_url(url):
        timeout = CORE_OPS_TIMEOUT
    return _call_json_orig(method, url, payload, timeout=timeout)


def cognitive_already_answered(body):
    """True si /turn ya entregó respuesta usable sin pedir Core."""
    if not isinstance(body, dict):
        return False
    if isinstance(body.get("core_channel"), dict) and body.get("core_channel"):
        return False
    app = body.get("app_channel") if isinstance(body.get("app_channel"), dict) else {}
    reply = (
        app.get("client_response")
        or body.get("reply")
        or body.get("message")
        or body.get("content")
    )
    if not reply:
        return False
    status = str(app.get("status") or body.get("status") or "").upper()
    if status in {
        "VALID_CONTRACT",
        "NEED_CLARIFICATION",
        "NEED_DISAMBIGUATION",
        "OUT_OF_SCOPE",
        "VALIDATION_ERROR",
    }:
        return True
    return True


def prefer_cognitive_over_failed_core(cognitive_body, core_fail_response, operation_request):
    if cognitive_already_answered(cognitive_body):
        out = dict(cognitive_body) if isinstance(cognitive_body, dict) else {"reply": str(cognitive_body)}
        out.setdefault("core_skipped", True)
        out["core_skip_reason"] = "cognitive_answered_or_core_unreachable"
        if isinstance(core_fail_response, dict):
            out["core_error"] = core_fail_response.get("body") or core_fail_response
        return out
    return {
        "error": "core_operation_failed",
        "operation_request": operation_request,
        "detail": (core_fail_response or {}).get("body") if isinstance(core_fail_response, dict) else core_fail_response,
    }

'''

OLD_BLOCK = '''    operation_request = extract_operation_request(cognitive_body, cognitive_payload)

    if not operation_request:
        operation_request = cognitive_response_to_operation_request(
            cognitive_body,
            cognitive_payload,
            raw_text
        )

    if not operation_request:
        if isinstance(cognitive_body, dict):
            cognitive_body.setdefault("conversation_id", payload.get("conversation_id"))
            cognitive_body.setdefault("session_id", payload.get("session_id"))
            cognitive_body.setdefault("subject_token", payload.get("subject_token"))
            cognitive_body.setdefault("session_status", payload.get("session_status"))

        record_session_turn(payload, raw_text, cognitive_body)
        return cognitive_body

    core_response = call_json("POST", CORE_OPERATIONS_URL, operation_request)

    if not core_response["ok"]:
        response = {
            "error": "core_operation_failed",
            "operation_request": operation_request,
            "detail": core_response["body"]
        }
        record_session_turn(payload, raw_text, response)
        return response

    response = render_operation(
        operation_request,
        core_response["body"],
        raw_text
    )

    record_session_turn(payload, raw_text, response)
    return response
'''

NEW_BLOCK = '''    # Preferir respuesta cognitiva si ya está completa (lab / snapshot).
    if cognitive_already_answered(cognitive_body):
        if isinstance(cognitive_body, dict):
            cognitive_body.setdefault("conversation_id", payload.get("conversation_id"))
            cognitive_body.setdefault("session_id", payload.get("session_id"))
            cognitive_body.setdefault("subject_token", payload.get("subject_token"))
            cognitive_body.setdefault("session_status", payload.get("session_status"))
            cognitive_body["core_skipped"] = True
            cognitive_body["core_skip_reason"] = "cognitive_already_answered"
        record_session_turn(payload, raw_text, cognitive_body)
        return cognitive_body

    operation_request = extract_operation_request(cognitive_body, cognitive_payload)

    if not operation_request:
        operation_request = cognitive_response_to_operation_request(
            cognitive_body,
            cognitive_payload,
            raw_text
        )

    if not operation_request:
        if isinstance(cognitive_body, dict):
            cognitive_body.setdefault("conversation_id", payload.get("conversation_id"))
            cognitive_body.setdefault("session_id", payload.get("session_id"))
            cognitive_body.setdefault("subject_token", payload.get("subject_token"))
            cognitive_body.setdefault("session_status", payload.get("session_status"))

        record_session_turn(payload, raw_text, cognitive_body)
        return cognitive_body

    core_response = call_json("POST", CORE_OPERATIONS_URL, operation_request)

    if not core_response["ok"]:
        response = prefer_cognitive_over_failed_core(
            cognitive_body, core_response, operation_request
        )
        if isinstance(response, dict):
            response.setdefault("conversation_id", payload.get("conversation_id"))
            response.setdefault("session_id", payload.get("session_id"))
            response.setdefault("subject_token", payload.get("subject_token"))
            response.setdefault("session_status", payload.get("session_status"))
        record_session_turn(payload, raw_text, response)
        return response

    response = render_operation(
        operation_request,
        core_response["body"],
        raw_text
    )

    record_session_turn(payload, raw_text, response)
    return response
'''


def _sudo(client: paramiko.SSHClient, cmd: str) -> tuple[int, str]:
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=120)
    stdin.write(PASSWORD + "\n")
    stdin.flush()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, (out + err).strip()


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    sftp = client.open_sftp()
    with sftp.open(REMOTE, "r") as f:
        text = f.read().decode("utf-8", errors="replace")

    if MARKER in text and "cognitive_already_answered(cognitive_body)" in text:
        print("Patch already applied")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup = f"{REMOTE}.bak.skipcore.{stamp}"
        code, out = _sudo(client, f"cp {REMOTE} {backup} && echo BACKUP_OK")
        print(out[-400:])
        if code != 0:
            print("backup failed")
            return 1

        if MARKER not in text:
            anchor = "PENDING_OPERATIONS = {}"
            idx = text.find(anchor)
            if idx < 0:
                print("ERROR: anchor PENDING_OPERATIONS not found")
                return 1
            insert_at = idx + len(anchor)
            text = text[:insert_at] + "\n" + HELPER + text[insert_at:]

        if OLD_BLOCK not in text:
            print("ERROR: target chat_front block not found")
            print("occurrences extract:", text.count(
                "operation_request = extract_operation_request(cognitive_body, cognitive_payload)"
            ))
            return 1

        last = text.rfind(OLD_BLOCK)
        text = text[:last] + NEW_BLOCK + text[last + len(OLD_BLOCK) :]

        local = Path(tempfile.gettempdir()) / "mcp_main_patched.py"
        local.write_text(text, encoding="utf-8", newline="\n")
        remote_tmp = "/tmp/mcp_main_patched.py"
        sftp.put(str(local), remote_tmp)
        code, out = _sudo(client, f"cp {remote_tmp} {REMOTE} && chown root:root {REMOTE} && echo WRITE_OK")
        print(out[-400:])
        if code != 0:
            return 1
        print("main.py patched")

    sftp.close()

    for cmd in [
        f"python3 -m py_compile {REMOTE} && echo SYNTAX_OK",
        "systemctl restart genesis-mcp-bridge",
        "sleep 2; systemctl is-active genesis-mcp-bridge; curl -sS -m 5 http://127.0.0.1:8080/health || true",
    ]:
        print("=" * 40, cmd[:70])
        code, out = _sudo(client, cmd)
        print(out[-2000:])
        if code != 0 and "py_compile" in cmd:
            return 1

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
