#!/usr/bin/env python3
"""Post-deploy probes from PC + orchestrate remote redis probe."""
from __future__ import annotations

import json
import os
import shlex
import sys
import uuid
from pathlib import Path
from urllib import error, request

import paramiko

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "works" / "azure_mejora" / "deploy_vpn_20260921"
BASE = os.environ.get("GENESIS_VALIDATE_BASE", "http://20.127.25.24:8447")
HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
CUSTOMER = "726588"


def password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
    if not pw:
        raise SystemExit("NO_PASSWORD")
    return pw


def http_json(path: str, payload: dict | None = None, timeout: float = 120) -> dict:
    url = BASE.rstrip("/") + path
    if payload is None:
        req = request.Request(url, method="GET")
    else:
        data = json.dumps(payload).encode()
        req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return {"http": resp.status, "body": json.loads(resp.read().decode())}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw[:500]}
        return {"http": exc.code, "body": body}


def reply_of(body: dict) -> str:
    app = body.get("app_channel") or {}
    return str(
        body.get("reply")
        or body.get("message")
        or body.get("client_response")
        or app.get("client_response")
        or ""
    )


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    out: dict = {"base": BASE}

    for path in ("/health", "/ready/redis"):
        r = http_json(path)
        out[path] = r
        print(path, r.get("http"), str(r.get("body"))[:200])

    conv = str(uuid.uuid4())
    ctx = http_json(
        "/orch/context",
        {"customer_id": CUSTOMER, "conversation_id": conv, "allow_lab_fallback": True, "portfolio": "qa_726588_contract_demo.json"},
    )
    out["context"] = {"http": ctx["http"], "status": (ctx.get("body") or {}).get("status")}
    print("context", out["context"])

    questions = [
        "Qué significa el saldo disponible",
        "Dime la misión y la visión",
        "¿Tengo algún préstamo o tarjeta con un pago próximo? Si es así, dime cuánto debo pagar y cuándo.",
        "Compárame Visa Platinum y Visa Infinite.",
    ]
    turns = []
    for q in questions:
        t = http_json(
            "/turn",
            {
                "question": q,
                "customer_id": CUSTOMER,
                "conversation_id": conv if "próximo" not in q and "Platinum" not in q else str(uuid.uuid4()),
                "context_info": False,
                "channel": {"type": "web", "entrypoint": "deploy_smoke"},
            },
            timeout=150,
        )
        # load context for new convs
        if t.get("http") == 422:
            # retry after fresh context
            c2 = str(uuid.uuid4())
            http_json(
                "/orch/context",
                {"customer_id": CUSTOMER, "conversation_id": c2, "allow_lab_fallback": True, "portfolio": "qa_726588_contract_demo.json"},
            )
            t = http_json(
                "/turn",
                {
                    "question": q,
                    "customer_id": CUSTOMER,
                    "conversation_id": c2,
                    "context_info": False,
                    "channel": {"type": "web", "entrypoint": "deploy_smoke"},
                },
                timeout=150,
            )
        body = t.get("body") or {}
        rep = reply_of(body)
        row = {
            "question": q,
            "http": t.get("http"),
            "reply_len": len(rep),
            "reply_prefix": rep[:300],
            "has_window": "ventana" in rep.lower() or "30" in rep and "día" in rep.lower(),
            "inference_count": body.get("inference_count"),
        }
        turns.append(row)
        print("TURN", q[:40], row["http"], row["reply_len"], row["reply_prefix"][:120].replace("\n", " "))

    out["smoke_turns"] = turns
    (EVID / "smoke_public.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Remote redis probe using service .env
    pw = password()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=pw, timeout=40, look_for_keys=False, allow_agent=False)
    remote = r"""
set -e
APP=/opt/genesis-cognitive-8447/Genesis_v2
cd "$APP"
set -a
# shellcheck disable=SC1091
source .env
set +a
"$APP/.venv/bin/python" scripts/redis_entra_ops_probe.py --cas --lock --json
"""
    wrapped = f"echo {shlex.quote(pw)} | sudo -S -u genesis -p '' bash -lc {shlex.quote(remote)}"
    _i, stdout, stderr = c.exec_command(wrapped, timeout=180)
    raw = (stdout.read() + stderr.read()).decode("utf-8", "replace").replace(pw, "***")
    (EVID / "redis_entra_ops_probe.txt").write_text(raw, encoding="utf-8")
    print("REDIS_PROBE\n", raw[-1500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
