"""Harness manual Redis+HTTP — no se ejecuta en CI sin Redis.

Uso: ver works/REDIS_CONCURRENCY_PROCEDURE_1C.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _wait_barrier(barrier_dir: Path, name: str, roles: int = 2, timeout_s: float = 30.0) -> None:
    barrier_dir.mkdir(parents=True, exist_ok=True)
    mine = barrier_dir / f"{name}-{os.getpid()}.ready"
    mine.write_text("1", encoding="utf-8")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        ready = list(barrier_dir.glob(f"{name}-*.ready"))
        if len(ready) >= roles:
            time.sleep(0.05)
            return
        time.sleep(0.02)
    raise TimeoutError(f"barrier {name} timeout")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=("A", "B"))
    parser.add_argument("--barrier-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8447")
    args = parser.parse_args()

    if not os.getenv("GENESIS_REDIS_URL"):
        print("GENESIS_REDIS_URL requerido", file=sys.stderr)
        return 2

    import urllib.request

    barrier = Path(args.barrier_dir)
    conv = "redis-harness-shared"

    def post_turn(payload: dict) -> tuple[int, dict]:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{args.base_url.rstrip('/')}/turn",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
                return resp.status, body
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                body = json.loads(raw)
            except Exception:
                body = {"raw": raw}
            return exc.code, body

    _wait_barrier(barrier, "turn-overlap")
    code, body = post_turn(
        {
            "question": f"¿Cuál es mi tasa? role={args.role}",
            "conversation_id": conv,
            "customer_id": "SYN-REDIS",
        }
    )
    print(json.dumps({"role": args.role, "case": "turn_overlap", "http": code, "status": body.get("status")}, ensure_ascii=False))
    if code != 200 or body.get("client_response") is None and not body.get("reply"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
