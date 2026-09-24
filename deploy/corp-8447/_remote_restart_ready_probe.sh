#!/bin/bash
# Restart clean + timed endpoint probes (no secrets).
set -euo pipefail
APP=/opt/genesis-cognitive-8447/Genesis_v2
PY="$APP/.venv/bin/python"

echo "=== RESTART ==="
sudo systemctl restart genesis-cognitive-8447.service
sleep 5
systemctl is-active genesis-cognitive-8447
PID=$(systemctl show -p MainPID --value genesis-cognitive-8447)
echo "MainPID=$PID"
tr '\0' '\n' < /proc/$PID/environ | grep -E '^(GENESIS_ENV|GENESIS_REDIS_AUTH_MODE|GENESIS_SESSION_BACKEND|GENESIS_REDIS_REQUIRED|GENESIS_SEMANTIC_MODE)=' || echo MISSING_KEYS
tr '\0' '\n' < /proc/$PID/environ | grep -E '^(GENESIS_REDIS_URL|GENESIS_CONV_LOCK_REDIS_URL)=' | sed 's/=.*/=SET/' || echo MISSING_URLS

echo "=== HEALTH_TIMED ==="
curl -sS -m 5 -w ' HTTP:%{http_code} T:%{time_total}\n' http://127.0.0.1:8447/health

echo "=== READY_REDIS_TIMED ==="
curl -sS -m 12 -w '\nHTTP:%{http_code} T:%{time_total}\n' http://127.0.0.1:8447/ready/redis || echo "READY_FAIL=$?"

echo "=== INPROC_READY_SIM ==="
ENVF="$APP/.env"
export PYTHONPATH="$APP/src${PYTHONPATH:+:$PYTHONPATH}"
while IFS= read -r line; do
  case "$line" in
    GENESIS_REDIS_*|GENESIS_CONV_LOCK_*|GENESIS_SESSION_*|GENESIS_SNAPSHOT_*|GENESIS_ENV=*|GENESIS_SEMANTIC_MODE=*)
      key="${line%%=*}"; val="${line#*=}"
      val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
      export "$key=$val"
      ;;
  esac
done < <(grep -E '^(GENESIS_REDIS_|GENESIS_CONV_LOCK_|GENESIS_SESSION_|GENESIS_SNAPSHOT_|GENESIS_ENV=|GENESIS_SEMANTIC_MODE=)' "$ENVF" || true)
timeout 20 "$PY" - <<'PY' || echo "SIM_FAIL=$?"
import json, time, os
print("env", os.getenv("GENESIS_ENV"), os.getenv("GENESIS_REDIS_AUTH_MODE"), os.getenv("GENESIS_SESSION_BACKEND"))
t0=time.time()
from genesis_cognitive.context.redis_session_store import build_session_store
store=build_session_store()
print("store", type(store).__name__, "ping", store.ping(), "t", round(time.time()-t0,2))
t1=time.time()
from genesis_cognitive.context.conversation_gate import get_conversation_gate, conversation_gate_backend_name
gate=get_conversation_gate()
print("gate", conversation_gate_backend_name(gate), "t", round(time.time()-t1,2))
from genesis_cognitive.context.redis_client_factory import diagnose_redis_backends
lock_client=getattr(gate, "_redis", None)
diag=diagnose_redis_backends(session_store=store, lock_client=lock_client)
diag["lock_backend"]=conversation_gate_backend_name(gate)
print(json.dumps(diag))
print("total", round(time.time()-t0,2))
PY

echo "=== JOURNAL ==="
sudo journalctl -u genesis-cognitive-8447 --since "2 min ago" --no-pager | tail -50

echo "DONE_RESTART_PROBE"
