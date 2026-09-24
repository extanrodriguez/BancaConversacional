#!/usr/bin/env python3
import json
import time
import urllib.request
from pathlib import Path

key = next(
    l.split("=", 1)[1].strip().strip("'\"" )
    for l in Path("/opt/genesis-rag/.env").read_text(encoding="utf-8").splitlines()
    if l.startswith("GENESIS_API_KEY=")
)

questions = [
    "hola",
    "quiero saber el balance de mi cuenta",
    "dame el balance de mis cuentas",
]

for q in questions:
    cid = f"t-{int(time.time() * 1000)}"
    payload = json.dumps(
        {"question": q, "top_k": 3, "conversation_id": cid, "client_id": "usuario1"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:8000/chat/front?x-api-key={key}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    ms = int((time.time() - t0) * 1000)
    print(f"{ms:4d}ms | {q} -> {body.get('status')} | {(body.get('reply') or '')[:140]}")
