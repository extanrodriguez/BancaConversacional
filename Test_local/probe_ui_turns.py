"""Simula login UI + varios turnos contra /turn."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from orquestador_local import load_portfolio  # noqa: E402


def post(path: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"http://127.0.0.1:8445{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode())
    except Exception as exc:
        if hasattr(exc, "read"):
            body = exc.read().decode("utf-8", errors="replace")
            return getattr(exc, "code", 500), {"error": body}
        return 500, {"error": str(exc)}


def main() -> int:
    status, login = post("/lab/login", {"customer_id": "TEST-QA-001"})
    print("login", status, login.get("status"))
    if status != 200:
        print(login)
        return 1

    cid = login["conversation_id"]
    questions = [
        "¿Cuál es mi saldo?",
        "¿Cuál es mi límite?",
        "¿Cuándo corta mi tarjeta?",
        "Muéstrame mis movimientos",
        "Necesito transferir dinero",
    ]
    fails = 0
    for q in questions:
        st, data = post(
            "/turn",
            {"question": q, "customer_id": "TEST-QA-001", "conversation_id": cid},
        )
        app = data.get("app_channel") or {}
        ok = st == 200 and app.get("client_response")
        mark = "OK" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"{mark} HTTP {st} | {app.get('status')} | {q}")
        if not ok:
            print(" ", data.get("error") or data)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
