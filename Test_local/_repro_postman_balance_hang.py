"""Reproducir flujo Postman: productos → balance en varios endpoints."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
CUSTOMER = "TEST-QA-001"


def post(url: str, payload: dict, timeout: int = 70) -> tuple[float, int, dict | str]:
    raw = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            dt = time.time() - t0
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = body[:500]
            return dt, resp.status, data
    except urllib.error.HTTPError as exc:
        dt = time.time() - t0
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = body[:500]
        return dt, exc.code, data
    except Exception as exc:  # noqa: BLE001
        return time.time() - t0, 0, {"error": type(exc).__name__, "message": str(exc)}


def summarize(data: dict | str) -> str:
    if not isinstance(data, dict):
        return str(data)[:180]
    app = data.get("app_channel") if isinstance(data.get("app_channel"), dict) else {}
    reply = (
        data.get("reply")
        or data.get("message")
        or data.get("content")
        or app.get("client_response")
        or data.get("error")
        or ""
    )
    return (
        f"err={data.get('error')} skip={data.get('core_skipped')} "
        f"status={data.get('status') or app.get('status')} "
        f"reply={(str(reply)[:140]).replace(chr(10), ' ')}"
    )


def run_pair(label: str, base_chat_url: str, *, with_context: bool) -> None:
    cid = f"pm-{uuid.uuid4().hex[:8]}"
    print("\n====", label, "conv=", cid)
    if with_context:
        dt, code, data = post(
            f"http://{HOST}:8447/orch/context",
            {"customer_id": CUSTOMER, "allow_lab_fallback": True, "conversation_id": cid},
            timeout=30,
        )
        print(f"context {code} {dt:.2f}s {data.get('status') if isinstance(data, dict) else data}")

    common = {
        "customer_id": CUSTOMER,
        "client_id": CUSTOMER,
        "subject_token": f"pm-{cid}",
        "conversation_id": cid,
    }
    for q in [
        "cuales son mis productos?",
        "cual es el saldo de la cuenta de ahorros terminada en 63641?",
    ]:
        payload = {
            **common,
            "question": q,
            "message": q,
            "raw_text": q,
        }
        dt, code, data = post(base_chat_url, payload)
        print(f"{dt:5.2f}s HTTP {code} | {q[:48]}")
        print("   ", summarize(data))


def main() -> None:
    # 1) Simulador path
    run_pair("8447 /orch/chat/front", f"http://{HOST}:8447/orch/chat/front", with_context=True)
    # 2) Cognitiva directa (como Postman a /turn)
    run_pair("8447 /turn", f"http://{HOST}:8447/turn", with_context=True)
    # 3) MCP directo :8080
    run_pair("8080 /chat/front", f"http://{HOST}:8080/chat/front", with_context=True)
    # 4) Proxy APK :8000 si existe
    run_pair("8000 /chat/front", f"http://{HOST}:8000/chat/front", with_context=True)


if __name__ == "__main__":
    main()
