#!/bin/bash
set -euo pipefail
APP=/opt/genesis-cognitive-8447/Genesis_v2
PY="$APP/.venv/bin/python"
ENVF="$APP/.env"
export PYTHONPATH="$APP/src"
while IFS= read -r line; do
  case "$line" in
    GENESIS_REDIS_*|GENESIS_CONV_LOCK_*|GENESIS_SESSION_*|GENESIS_SNAPSHOT_*|GENESIS_ENV=*)
      key="${line%%=*}"; val="${line#*=}"
      val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
      export "$key=$val"
      ;;
  esac
done < <(grep -E '^(GENESIS_REDIS_|GENESIS_CONV_LOCK_|GENESIS_SESSION_|GENESIS_SNAPSHOT_|GENESIS_ENV=)' "$ENVF" || true)

echo "=== WARM_THEN_USE_IN_LOOP ==="
timeout 20 "$PY" - <<'PY' || echo "EXIT=$?"
import asyncio, time
from genesis_cognitive.context.conversation_gate import reset_conversation_gate_for_tests, get_conversation_gate, conversation_gate_backend_name
from genesis_cognitive.context.redis_session_store import build_session_store
from genesis_cognitive.context.redis_client_factory import diagnose_redis_backends

reset_conversation_gate_for_tests(None)
# warm BEFORE loop (like create_app startup)
store=build_session_store()
gate=get_conversation_gate()
print("warmed", type(store).__name__, conversation_gate_backend_name(gate))

async def main():
    t0=time.time()
    print("ping store in loop", store.ping(), "t", round(time.time()-t0,2))
    t1=time.time()
    # second get should be cached
    g2=get_conversation_gate()
    print("cached gate", g2 is gate, "t", round(time.time()-t1,2))
    t2=time.time()
    diag=diagnose_redis_backends(session_store=store, lock_client=getattr(gate,"_redis",None))
    print("diag ok", diag.get("ok"), diag.get("session_ping"), diag.get("lock_ping"), "t", round(time.time()-t2,2))
    # try lock acquire (sync) inside loop
    t3=time.time()
    acquired=gate._redis.set(name="genesis:probe:locktest", value="1", nx=True, ex=5) if gate._redis else None
    print("setnx", acquired, "t", round(time.time()-t3,2))
    if gate._redis:
        gate._redis.delete("genesis:probe:locktest")

asyncio.run(main())
print("ALL_OK")
PY
echo DONE
