#!/usr/bin/env python3
"""Probe operativo Redis (misma fábrica que sesiones/candados).

No imprime tokens ni claves. Uso:
  GENESIS_REDIS_AUTH_MODE=url GENESIS_REDIS_URL=redis://127.0.0.1:6379/0 \\
    python scripts/redis_entra_ops_probe.py

  En la VM QA (Entra + PE):
  set -a; source /path/to/redis_qa.env; set +a
  python scripts/redis_entra_ops_probe.py --cas --lock
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Redis Entra/ops probe (no secrets)")
    parser.add_argument("--cas", action="store_true", help="Probar WATCH/MULTI CAS de sesión")
    parser.add_argument("--lock", action="store_true", help="Probar SET NX + scripts liberacion")
    parser.add_argument("--json", action="store_true", help="Salida JSON")
    args = parser.parse_args()

    from genesis_cognitive.context.redis_client_factory import (
        create_and_ping,
        diagnose_redis_backends,
        lock_redis_url,
        redis_auth_mode,
        session_redis_url,
    )

    report: dict = {
        "auth_mode": redis_auth_mode(),
        "session_url_set": bool(session_redis_url()),
        "lock_url_set": bool(lock_redis_url()),
        "steps": {},
    }

    sess_url = session_redis_url()
    lock_url = lock_redis_url()
    if not sess_url:
        report["ok"] = False
        report["error"] = "GENESIS_REDIS_URL empty"
        _emit(report, args.json)
        return 2

    try:
        sess = create_and_ping(sess_url, purpose="session")
        report["steps"]["session_ping"] = True
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["steps"]["session_ping"] = False
        report["error"] = f"session:{type(exc).__name__}"
        _emit(report, args.json)
        return 3

    try:
        lock = create_and_ping(lock_url or sess_url, purpose="lock")
        report["steps"]["lock_ping"] = True
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["steps"]["lock_ping"] = False
        report["error"] = f"lock:{type(exc).__name__}"
        _emit(report, args.json)
        return 3

    # Clave sintética UUID + TTL corto
    key = f"genesis:probe:{uuid.uuid4().hex}"
    try:
        sess.setex(key, 30, "ok")
        val = sess.get(key)
        sess.delete(key)
        report["steps"]["set_get_del"] = val == "ok"
    except Exception as exc:  # noqa: BLE001
        report["steps"]["set_get_del"] = False
        report["error"] = f"kv:{type(exc).__name__}"
        report["ok"] = False
        _emit(report, args.json)
        return 4

    if args.lock:
        from genesis_cognitive.context.conversation_gate import ConversationGate

        gate = ConversationGate(redis_client=lock, redis_required=True, lock_ttl_s=5)
        token = f"probe-{uuid.uuid4().hex}"
        ok = gate._acquire_redis_sync("probe-conv", token, timeout_s=2.0)
        still = gate._still_owner_sync("probe-conv", token) if ok else False
        renewed = gate._renew_redis_sync("probe-conv", token) if ok else False
        if ok:
            gate._release_redis_sync("probe-conv", token)
        report["steps"]["lock_nx"] = bool(ok and still and renewed)

    if args.cas:
        from genesis_cognitive.context.reactive_store import SessionState
        from genesis_cognitive.context.redis_session_store import RedisSessionStore

        store = RedisSessionStore(redis_client=sess, redis_url=sess_url)
        cid = f"probe-cas-{uuid.uuid4().hex[:12]}"
        store.put_session(cid, SessionState(customer_id="probe"), expected_revision=0)
        s1 = store.get_session(cid)
        assert s1 is not None
        rev = int(s1.revision)
        store.put_session(cid, s1, expected_revision=rev)
        conflict = False
        try:
            store.put_session(cid, s1, expected_revision=0)
        except Exception:
            conflict = True
        store.delete_session(cid)
        report["steps"]["cas_conflict"] = conflict

    report["diagnose"] = diagnose_redis_backends()
    report["ok"] = all(
        v is True for k, v in report["steps"].items() if k != "diagnose"
    ) and bool(report["steps"])
    _emit(report, args.json)
    return 0 if report["ok"] else 5


def _emit(report: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print("auth_mode", report.get("auth_mode"))
    print("ok", report.get("ok"))
    for k, v in (report.get("steps") or {}).items():
        print(f"  {k}={v}")
    if report.get("error"):
        print("error", report["error"])


if __name__ == "__main__":
    raise SystemExit(main())
