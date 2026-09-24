#!/usr/bin/env python3
"""Reproduce AttributeError on live azure_plan path with real app resolver."""
from __future__ import annotations

import asyncio
import os
import time
import traceback
import uuid

os.chdir("/opt/genesis-cognitive-8447/Genesis_v2")
os.environ.setdefault("PYTHONPATH", "/opt/genesis-cognitive-8447/Genesis_v2/src")

# Load GENESIS_/AZURE_ from .env without printing secrets
env_path = "/opt/genesis-cognitive-8447/Genesis_v2/.env"
if os.path.isfile(env_path):
    with open(env_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.startswith(("GENESIS_", "AZURE_")):
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)

from genesis_cognitive.demo.contract_inspector_app import create_app
from genesis_cognitive.brain.azure_plan_turn import run_azure_plan_path
from genesis_cognitive.context.reactive_store import SessionState


async def main() -> None:
    app = create_app()
    # Prefer lifespan-initialized state when present
    store = getattr(app.state, "store", None)
    resolver = getattr(app.state, "resolver", None)
    mib = getattr(app.state, "model_input_builder", None)
    ca = getattr(app.state, "context_assembler", None)
    iv = getattr(app.state, "input_validator", None)
    print("deps", {
        "store": type(store).__name__ if store else None,
        "resolver": type(resolver).__name__ if resolver else None,
        "mib": type(mib).__name__ if mib else None,
        "ca": type(ca).__name__ if ca else None,
        "iv": type(iv).__name__ if iv else None,
        "semantic_mode": os.environ.get("GENESIS_SEMANTIC_MODE"),
    })
    if not all([store, resolver, mib, ca, iv]):
        # Fallback: inspect module-level from create_app closure via /turn route
        print("MISSING_APP_STATE — probing route handlers")
        return

    snap = store.get_snapshot("726588")
    print("snap_products", None if snap is None else len(getattr(snap, "products", ()) or ()))
    sess = SessionState(customer_id="726588", snapshot=snap)
    questions = [
        "¿Con cuánto puedo contar?",
        "¿Cuál es el saldo de mi cuenta?",
        "La tasa de mi préstamo y qué significa",
        "¿Y el saldo contable?",
    ]
    for q in questions:
        print("=== Q:", q[:60])
        try:
            out = await run_azure_plan_path(
                question=q,
                safe_question=q,
                session_state=sess,
                history=[],
                customer_snapshot=snap,
                resolver=resolver,
                model_input_builder=mib,
                context_assembler=ca,
                input_validator=iv,
                conv_id=f"diag-{uuid.uuid4().hex[:8]}",
                customer_id="726588",
                turn_number=1,
                azure_model=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
                prompt_version="diag",
                request_start=time.perf_counter(),
            )
            trace = (out.get("decision_trace") or [{}])[0].get("output") or {}
            print(
                "status", out.get("status"),
                "intent", out.get("intent_id"),
                "inf", out.get("inference_count"),
                "route", trace.get("route_source") or trace.get("error_class"),
                "stage", trace.get("error_stage") or trace.get("brain_source"),
            )
        except Exception as exc:
            print("RAISED", type(exc).__name__, str(exc)[:200])
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
