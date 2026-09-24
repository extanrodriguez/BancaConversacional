r"""Local UI Proxy — serves static Inspector HTML and proxies API to Azure cognitive.

Architecture:
  Browser (localhost:8080)
    ├── GET /           → static index.html (from src/genesis_cognitive/demo/static/)
    ├── GET /static/*   → static files
    ├── POST /inspect   → proxy to COGNITIVE_BASE_URL/inspect
    ├── POST /turn      → proxy to COGNITIVE_BASE_URL/turn
    ├── POST /contract-lab/* → proxy to COGNITIVE_BASE_URL/contract-lab/*
    ├── GET  /health    → proxy to COGNITIVE_BASE_URL/health
    ├── GET  /customers → proxy to COGNITIVE_BASE_URL/customers
    └── GET  /config    → proxy to COGNITIVE_BASE_URL/config

Usage:
    set COGNITIVE_BASE_URL=http://20.121.197.165:8445
    .\.venv\Scripts\python.exe scripts/ui_proxy.py

    Browser: http://localhost:8080
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).parent.parent
STATIC_DIR = PROJECT_ROOT / "src" / "genesis_cognitive" / "demo" / "static"

COGNITIVE_BASE_URL = os.environ.get("COGNITIVE_BASE_URL", "http://20.121.197.165:8445")
PROXY_PORT = int(os.environ.get("UI_PROXY_PORT", "8080"))

app = FastAPI(title="Genesis UI Proxy (local)")

# Async HTTP client for proxying
_client = httpx.AsyncClient(base_url=COGNITIVE_BASE_URL, timeout=180.0)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/health")
async def health_proxy() -> Response:
    r = await _client.get("/health")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@app.get("/customers")
async def customers_proxy() -> Response:
    r = await _client.get("/customers")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@app.get("/config")
async def config_proxy() -> Response:
    r = await _client.get("/config")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@app.post("/inspect")
async def inspect_proxy(request: Request) -> Response:
    body = await request.body()
    r = await _client.post("/inspect", content=body, headers={"Content-Type": "application/json"})
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@app.post("/turn")
async def turn_proxy(request: Request) -> Response:
    body = await request.body()
    r = await _client.post("/turn", content=body, headers={"Content-Type": "application/json"})
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@app.post("/contract-lab/dispatch")
async def dispatch_proxy(request: Request) -> Response:
    body = await request.body()
    qs = str(request.url.query)
    url = f"/contract-lab/dispatch?{qs}" if qs else "/contract-lab/dispatch"
    r = await _client.post(url, content=body, headers={"Content-Type": "application/json"})
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@app.post("/contract-lab/validate")
async def validate_proxy(request: Request) -> Response:
    body = await request.body()
    r = await _client.post("/contract-lab/validate", content=body, headers={"Content-Type": "application/json"})
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@app.post("/rag/query")
async def rag_proxy(request: Request) -> Response:
    body = await request.body()
    r = await _client.post("/rag/query", content=body, headers={"Content-Type": "application/json"})
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


# Serve static assets (JS, CSS, images if any)
if (STATIC_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR / "static")), name="static")


def main() -> None:
    print("=" * 60)
    print("Genesis UI Proxy (local)")
    print("=" * 60)
    print(f"Cognitive backend: {COGNITIVE_BASE_URL}")
    print(f"UI:                http://localhost:{PROXY_PORT}")
    print(f"Static dir:        {STATIC_DIR}")
    print("=" * 60)
    print("Browser → localhost; API → Azure VM (privado con bypass)")
    print("Press Ctrl+C to stop.\n")
    uvicorn.run(app, host="127.0.0.1", port=PROXY_PORT, log_level="info")


if __name__ == "__main__":
    main()
