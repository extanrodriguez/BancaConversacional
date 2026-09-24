# -*- coding: utf-8 -*-
"""Probe connectivity: Azure OpenAI, Search, Redis — no secrets printed."""
from __future__ import annotations

import os
import socket
import ssl
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def has_value(v: str | None) -> bool:
    if not v:
        return False
    low = v.lower()
    return not any(x in low for x in ("changeme", "your_", "<", "xxx", "todo"))


def tcp_probe(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"ok {int((time.perf_counter()-t0)*1000)}ms"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    env = {}
    env.update(load_dotenv(ROOT / ".env"))
    env.update(load_dotenv(ROOT / "Test_local" / ".env.local"))
    # process env overrides
    for k, v in os.environ.items():
        if k.startswith(("AZURE_", "GENESIS_", "OPENAI_")):
            env[k] = v

    interesting = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_CHAT_DEPLOYMENT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_INDEX",
        "AZURE_SEARCH_API_KEY",
        "GENESIS_REDIS_URL",
        "GENESIS_CONV_LOCK_REDIS_URL",
        "GENESIS_REDIS_AUTH_MODE",
        "GENESIS_SESSION_BACKEND",
        "GENESIS_AZURE_BRAIN",
        "GENESIS_FOUNDRY_PROJECT_ENDPOINT",
    ]
    print("=== ENV (presence only) ===")
    for k in interesting:
        v = env.get(k)
        print(f"{k}: {'SET' if has_value(v) else 'missing/empty'}")

    aoai = (env.get("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    search = (env.get("AZURE_SEARCH_ENDPOINT") or "").rstrip("/")
    redis_url = env.get("GENESIS_REDIS_URL") or ""

    print("\n=== TCP probes ===")
    targets = []
    if aoai.startswith("https://"):
        targets.append(("AOAI", aoai.replace("https://", "").split("/")[0], 443))
    if search.startswith("https://"):
        targets.append(("SEARCH", search.replace("https://", "").split("/")[0], 443))
    # reported redis from plan
    targets.append(("REDIS_QA_REPORTED", "bsc-cognitive-redis-qa.eastus.redis.azure.net", 10000))
    if "://" in redis_url:
        # rediss://host:port/db
        hostport = redis_url.split("://", 1)[1].split("/")[0]
        host = hostport.split(":")[0]
        port = int(hostport.split(":")[1]) if ":" in hostport else 10000
        targets.append(("REDIS_ENV", host, port))
    # example search from corp
    targets.append(("SEARCH_CORP_EXAMPLE", "ai-search-genesis.search.windows.net", 443))

    for label, host, port in targets:
        ok, msg = tcp_probe(host, port)
        print(f"{label} {host}:{port} -> {'REACHABLE' if ok else 'UNREACHABLE'} ({msg})")

    print("\n=== az account ===")
    import subprocess

    try:
        r = subprocess.run(
            ["az", "account", "show", "--query", "{name:name,id:id,tenant:tenantId}", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        print("exit", r.returncode)
        if r.returncode == 0:
            print("logged_in: yes")
            # don't print full id if sensitive — print truncated
            import json

            data = json.loads(r.stdout)
            print("subscription_name:", data.get("name"))
            print("tenant_prefix:", str(data.get("tenant") or "")[:8] + "…")
        else:
            print("logged_in: no")
            print((r.stderr or r.stdout)[:300])
    except Exception as exc:
        print("az_cli:", type(exc).__name__, exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
