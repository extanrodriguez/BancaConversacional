#!/usr/bin/env python3
"""Parchea /opt/genesis-rag/app/main.py para proxyar /chat/front a 8447."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

MAIN = Path("/opt/genesis-rag/app/main.py")
PROXY_SRC = Path("/tmp/cognitive_front_proxy.py")
PROXY_DST = Path("/opt/genesis-rag/app/cognitive_front_proxy.py")

NEW_HANDLER = '''@app.post("/chat/front")
def chat_front(
    payload: dict,
    x_api_key: Optional[str] = Header(default=None),
    api_key_q: Optional[str] = Query(default=None, alias="x-api-key"),
):
    # APK envía x-api-key en query string; header también soportado.
    check_key(x_api_key or api_key_q)
    from app.cognitive_front_proxy import FrontChatRequest, proxy_to_cognitive
    req = FrontChatRequest(
        question=(payload.get("question") or payload.get("message") or payload.get("content") or payload.get("text") or ""),
        conversation_id=payload.get("conversation_id"),
        client_id=payload.get("client_id") or payload.get("customer_id"),
        top_k=payload.get("top_k") or 3,
        message=payload.get("message"),
        content=payload.get("content"),
        text=payload.get("text"),
    )
    return proxy_to_cognitive(req)

'''


def main() -> int:
    if not MAIN.exists():
        raise SystemExit(f"missing {MAIN}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    shutil.copy2(MAIN, MAIN.with_suffix(f".py.bak.{stamp}"))
    shutil.copy2(PROXY_SRC, PROXY_DST)

    text = MAIN.read_text(encoding="utf-8")
    if "from fastapi import FastAPI, Header, HTTPException, Query" not in text:
        text = text.replace(
            "from fastapi import FastAPI, Header, HTTPException",
            "from fastapi import FastAPI, Header, HTTPException, Query",
        )

    start = text.find('@app.post("/chat/front")')
    if start < 0:
        raise SystemExit("chat/front handler not found")
    nxt = text.find("\n@app.", start + 1)
    if nxt < 0:
        nxt = len(text)
    text = text[:start] + NEW_HANDLER + text[nxt:]
    MAIN.write_text(text, encoding="utf-8")
    print("OK patched", MAIN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
