#!/bin/bash
# Diagnose /ready/redis hang — no secrets.
set -euo pipefail
APP=/opt/genesis-cognitive-8447/Genesis_v2
PY="$APP/.venv/bin/python"
cd "$APP"

echo "=== UNIT ==="
systemctl is-active genesis-cognitive-8447
systemctl show genesis-cognitive-8447 -p MainPID -p ActiveState -p NRestarts --no-pager

echo "=== DEPS ==="
"$PY" -c "import redis; print('redis', redis.__version__)"
"$PY" -c "import redis_entraid; print('entraid_ok', getattr(redis_entraid,'__version__', '?'))" 2>&1 | head -5
"$PY" -c "from genesis_cognitive.context import redis_client_factory as f; print('factory', f.__file__)" 2>&1 | head -5
"$PY" -c "from genesis_cognitive.brain import azure_plan_turn; print('v4', azure_plan_turn.__file__)" 2>&1 | head -5

echo "=== ROUTES ==="
grep -n 'ready/redis\|/health' "$APP/src/genesis_cognitive/demo/contract_inspector_app.py" | head -10 || true

echo "=== DIAGNOSE_DIRECT ==="
# selective env load
ENV="$APP/.env"
while IFS= read -r line; do
  case "$line" in
    GENESIS_REDIS_*|GENESIS_CONV_LOCK_*|GENESIS_SESSION_*|GENESIS_SNAPSHOT_*|GENESIS_ENV=*)
      key="${line%%=*}"; val="${line#*=}"
      val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
      export "$key=$val"
      ;;
  esac
done < <(grep -E '^(GENESIS_REDIS_|GENESIS_CONV_LOCK_|GENESIS_SESSION_|GENESIS_SNAPSHOT_|GENESIS_ENV=)' "$ENV" || true)

timeout 25 "$PY" - <<'PY' || echo "DIAG_TIMEOUT_OR_FAIL=$?"
import json, time
t0=time.time()
from genesis_cognitive.context.redis_client_factory import diagnose_redis_backends, create_and_ping, session_redis_url, redis_auth_mode
print("auth_mode", redis_auth_mode())
print("url_set", bool(session_redis_url()))
print("url_scheme_host", (session_redis_url() or "").split("@")[-1][:80])
try:
    c=create_and_ping(session_redis_url(), purpose="session")
    print("create_and_ping_ok", True, "elapsed", round(time.time()-t0,2))
except Exception as e:
    print("create_and_ping_fail", type(e).__name__, str(e)[:180], "elapsed", round(time.time()-t0,2))
t1=time.time()
try:
    d=diagnose_redis_backends()
    print("diagnose", json.dumps(d, default=str)[:800])
    print("diagnose_elapsed", round(time.time()-t1,2))
except Exception as e:
    print("diagnose_fail", type(e).__name__, str(e)[:180], "elapsed", round(time.time()-t1,2))
PY

echo "=== READY_CURL ==="
timeout 20 curl -sS -m 18 -w '\nHTTP:%{http_code} TIME:%{time_total}\n' http://127.0.0.1:8447/ready/redis || echo "CURL_FAIL=$?"

echo "=== JOURNAL_TAIL ==="
sudo journalctl -u genesis-cognitive-8447 -n 60 --no-pager | grep -iE 'redis|entra|error|ready|traceback|exception' | tail -40 || true

echo "DONE_DIAG"
