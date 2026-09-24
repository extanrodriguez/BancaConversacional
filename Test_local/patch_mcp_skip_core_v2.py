"""Fix MCP patch: restaurar backup y aplicar helpers DESPUÉS de call_json."""
from __future__ import annotations

import os
import shlex
import sys
import tempfile
from pathlib import Path

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
PASSWORD = os.environ["SSH_DEPLOY_PASS"]
REMOTE = "/opt/genesis/mcp-bridge/main.py"
MARKER = "_mcp_skip_core_when_cognitive_answered_v2"

HELPER = r'''

# _mcp_skip_core_when_cognitive_answered_v2
CORE_OPS_TIMEOUT = int(os.getenv("CORE_OPS_TIMEOUT", "5"))


def cognitive_already_answered(body):
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
    return bool(reply)


def prefer_cognitive_over_failed_core(cognitive_body, core_fail_response, operation_request):
    if cognitive_already_answered(cognitive_body):
        out = dict(cognitive_body) if isinstance(cognitive_body, dict) else {"reply": str(cognitive_body)}
        out["core_skipped"] = True
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

NEW_BLOCK = '''    if cognitive_already_answered(cognitive_body):
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

    # Timeout corto para Core ops (evita UI "pensando" 45s)
    core_response = call_json("POST", CORE_OPERATIONS_URL, operation_request, timeout=CORE_OPS_TIMEOUT)

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


def sudo(client, cmd: str) -> tuple[int, str]:
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=90)
    stdin.write(PASSWORD + "\n")
    stdin.flush()
    out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="genesis", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    # Restaurar último backup skipcore si existe; si no, el de subject
    code, out = sudo(
        c,
        "ls -1t /opt/genesis/mcp-bridge/main.py.bak.skipcore.* 2>/dev/null | head -1",
    )
    backup = ""
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("/opt/genesis/mcp-bridge/main.py.bak"):
            backup = line
            break
    if not backup:
        code, out = sudo(c, "ls -1t /opt/genesis/mcp-bridge/main.py.bak.* 2>/dev/null | head -1")
        for line in out.splitlines():
            line = line.strip()
            if "main.py.bak" in line:
                backup = line
                break
    if not backup:
        print("ERROR: no backup found", out)
        return 1
    print("Restoring", backup)
    code, out = sudo(c, f"cp {backup} {REMOTE} && echo RESTORE_OK")
    print(out[-300:])
    if code != 0:
        return 1

    sftp = c.open_sftp()
    with sftp.open(REMOTE, "r") as f:
        text = f.read().decode("utf-8", errors="replace")

    if MARKER in text:
        print("v2 already present after restore? unexpected")
    else:
        # Insert helpers after call_json function — before extract_raw_text
        anchor = "\ndef extract_raw_text(payload: Dict[str, Any]) -> str:"
        if anchor not in text:
            print("ERROR: extract_raw_text anchor missing")
            return 1
        text = text.replace(anchor, HELPER + anchor, 1)

        if OLD_BLOCK not in text:
            print("ERROR: OLD_BLOCK not found after restore")
            return 1
        last = text.rfind(OLD_BLOCK)
        text = text[:last] + NEW_BLOCK + text[last + len(OLD_BLOCK) :]

        local = Path(tempfile.gettempdir()) / "mcp_main_v2.py"
        local.write_text(text, encoding="utf-8", newline="\n")
        sftp.put(str(local), "/tmp/mcp_main_v2.py")
        code, out = sudo(c, f"cp /tmp/mcp_main_v2.py {REMOTE} && chown root:root {REMOTE} && echo WRITE_OK")
        print(out[-300:])
        if code != 0:
            return 1

    sftp.close()

    for cmd in [
        f"python3 -m py_compile {REMOTE} && echo SYNTAX_OK",
        "systemctl restart genesis-mcp-bridge",
        "sleep 3; systemctl is-active genesis-mcp-bridge; curl -sS -m 5 http://127.0.0.1:8080/health || true",
    ]:
        code, out = sudo(c, cmd)
        print("=" * 40, cmd[:60])
        print(out[-1500:])
        if code != 0 and "py_compile" in cmd:
            return 1

    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
