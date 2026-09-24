"""Reproduce misión+visión en 8447 (FAQ local en VM + /turn + webhook)."""
from __future__ import annotations

import json
import os
import shlex
import sys

import paramiko


def main() -> int:
    password = os.environ["SSH_DEPLOY_PASS"]
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    q = "CUAL ES LA MISIÓN Y LA VISIÓN DE BANCO SANTA CRU?"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username="genesis",
        password=password,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )

    def run(cmd: str, timeout: int = 180) -> str:
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace")

    py = f"""
from genesis_cognitive.router.faq_guardrail import match_faq, apply_faq_guardrail, clear_faq_cache
clear_faq_cache()
q = {q!r}
hit = match_faq(q) or {{}}
ans = hit.get('answer') or ''
print('topic=', hit.get('topic'))
print('id=', hit.get('id'))
print('has_vision=', ('preferido' in ans.lower()) or ('**Vis' in ans))
print('---ANS---')
print(ans)
gr = apply_faq_guardrail(None, q, None)
print('---GR---')
print(gr[2] if gr else None)
"""
    print("==== match_faq on VM ====")
    print(
        run(
            "cd /opt/genesis-cognitive-8447/Genesis_v2 && "
            f".venv/bin/python -c {shlex.quote(py)}"
        )
    )

    turn_body = json.dumps(
        {
            "question": q,
            "customer_id": "726588",
            "client_id": "726588",
            "conversation_id": "test-mision-vision-1",
            "allow_lab_fallback": True,
        },
        ensure_ascii=False,
    )
    print("==== /turn ====")
    turn_cmd = (
        "curl -sS -m 90 -X POST http://127.0.0.1:8447/turn "
        "-H 'Content-Type: application/json' "
        f"-d {shlex.quote(turn_body)}"
    )
    turn_out = run(turn_cmd)
    print(turn_out[:2500])
    try:
        tj = json.loads(turn_out)
        reply = tj.get("client_response") or tj.get("reply") or ""
        print("TURN has_vision=", "preferido" in reply.lower() or "Visión" in reply or "Vision" in reply)
    except Exception as e:
        print("TURN parse err", e)

    wh_body = json.dumps(
        {"question": q, "allow_lab_fallback": True},
        ensure_ascii=False,
    )
    print("==== webhook ====")
    wh_cmd = (
        "curl -sS -m 90 -X POST http://127.0.0.1:8447/orch/webhook/chat "
        "-H 'Content-Type: application/json' -H 'ClientId: 726588' "
        f"-d {shlex.quote(wh_body)}"
    )
    wh_out = run(wh_cmd)
    print(wh_out[:2500])
    try:
        wj = json.loads(wh_out)
        reply = wj.get("reply") or ""
        print("WH has_vision=", "preferido" in reply.lower() or "Visión" in reply)
        print("WH reply=", reply[:800])
    except Exception as e:
        print("WH parse err", e)

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
