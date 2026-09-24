"""Mide latencia de consultas frecuentes contra /turn."""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from orquestador_local import load_portfolio  # noqa: E402

CASES = [
    "¿Cuál es mi saldo?",
    "¿Cuánto debo de mi préstamo?",
    "¿Cuál es mi límite?",
    "Hola",
    "Necesito transferir dinero",
]


def post(path: str, payload: dict) -> tuple[int, dict, int]:
    t0 = time.perf_counter()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"http://127.0.0.1:8445{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode())
    return resp.status, body, int((time.perf_counter() - t0) * 1000)


def main() -> None:
    env = load_portfolio("qa_andres_david.json")
    for q in CASES:
        cid = str(uuid.uuid4())
        post("/turn", {
            "question": None,
            "customer_id": "CUST_LOCAL",
            "conversation_id": cid,
            "context_info": True,
            "context_op": "load",
            "context": {"data": {"primerNombre": env.get("primerNombre"), "products": env.get("data")}},
        })
        st, data, ms = post("/turn", {
            "question": q,
            "customer_id": "CUST_LOCAL",
            "conversation_id": cid,
        })
        app = data.get("app_channel") or {}
        audit = data.get("audit") or {}
        print(f"{ms:4d}ms | HTTP {st} | {app.get('status')} | {q}")


if __name__ == "__main__":
    main()
