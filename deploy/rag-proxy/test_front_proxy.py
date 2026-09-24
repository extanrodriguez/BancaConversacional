#!/usr/bin/env python3
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

key = ""
for line in Path("/opt/genesis-rag/.env").read_text(encoding="utf-8").splitlines():
    if line.startswith("GENESIS_API_KEY="):
        key = line.split("=", 1)[1].strip().strip('"').strip("'")
        break

apk_key = "genesis-rag-temp-c04f313048e160f088601c96"
payload = json.dumps(
    {
        "question": "quiero saber el balance de mi cuenta",
        "top_k": 3,
        "conversation_id": "apk-test-1",
        "client_id": "usuario1",
    }
).encode("utf-8")

for kname, k in [("env", key), ("apk", apk_key)]:
    url = f"http://127.0.0.1:8000/chat/front?x-api-key={k}"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            print(kname, "OK", resp.status, int((time.time() - t0) * 1000), "ms")
            print(body[:400])
    except urllib.error.HTTPError as exc:
        print(kname, "HTTP", exc.code, int((time.time() - t0) * 1000), "ms")
        print(exc.read().decode("utf-8", errors="replace")[:400])
    except Exception as exc:
        print(kname, "ERR", exc)
