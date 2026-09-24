#!/bin/bash
# Prove Entra Redis deadlock inside running asyncio loop vs thread offload.
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

echo "=== ASYNC_LOOP_DEADLOCK_TEST ==="
timeout 15 "$PY" - <<'PY' || echo "ASYNC_TEST_EXIT=$?"
import asyncio, time
from genesis_cognitive.context.conversation_gate import reset_conversation_gate_for_tests, get_conversation_gate

reset_conversation_gate_for_tests(None)

async def main():
    t0=time.time()
    print("calling get_conversation_gate inside running loop...")
    gate=get_conversation_gate()
    print("OK gate", type(gate).__name__, "elapsed", round(time.time()-t0,2))

asyncio.run(main())
PY

echo "=== TO_THREAD_OFFLOAD_TEST ==="
timeout 15 "$PY" - <<'PY' || echo "THREAD_TEST_EXIT=$?"
import asyncio, time
from genesis_cognitive.context.conversation_gate import reset_conversation_gate_for_tests, get_conversation_gate

reset_conversation_gate_for_tests(None)

async def main():
    t0=time.time()
    print("calling get_conversation_gate via to_thread...")
    gate=await asyncio.to_thread(get_conversation_gate)
    print("OK gate", type(gate).__name__, "elapsed", round(time.time()-t0,2))

asyncio.run(main())
PY

echo "DONE_DEADLOCK"
