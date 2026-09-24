"""Smoke del cliente Foundry KB (requiere az login + flag).

Uso:
  az login
  $env:GENESIS_FOUNDRY_KB_AGENT="1"
  .\\.venv\\Scripts\\python.exe Test_local\\smoke_foundry_kb_agent.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("GENESIS_FOUNDRY_KB_AGENT", "1")

from genesis_cognitive.rag.foundry_kb_agent import ask_foundry_kb_agent, foundry_config


def main() -> int:
    cfg = foundry_config()
    print("config:", cfg)
    q = os.getenv("GENESIS_FOUNDRY_SMOKE_Q", "que es un certificado de deposito")
    print("question:", q)
    out = ask_foundry_kb_agent(q, display_name="Felix")
    print("status:", out.get("status"))
    print("ok:", out.get("ok"))
    if out.get("error"):
        print("error:", out["error"])
    print("answer:", (out.get("answer") or "")[:500])
    # Personal must be skipped
    skip = ask_foundry_kb_agent("cual es mi saldo")
    print("skip_personal:", skip.get("status"))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
