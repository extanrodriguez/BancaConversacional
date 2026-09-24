#!/bin/bash
# Post-merge: code markers, deps, /ready/redis, ops probe, concurrency HTTP.
set -euo pipefail
APP=/opt/genesis-cognitive-8447/Genesis_v2
PY="$APP/.venv/bin/python"
ENV="$APP/.env"
cd "$APP"

echo "=== CODE_MARKERS ==="
for f in \
  src/genesis_cognitive/context/redis_client_factory.py \
  src/genesis_cognitive/brain/azure_plan_turn.py \
  src/genesis_cognitive/brain/semantic_mode.py \
  scripts/redis_entra_ops_probe.py \
  deploy/corp-8447/redis_qa.env.example \
  tests/manual/redis_http_concurrency_harness.py
do
  if [ -f "$APP/$f" ]; then echo "OK $f"; else echo "MISS $f"; fi
done

echo "=== DEPS ==="
"$PY" -c "import redis; print('redis', redis.__version__)"
"$PY" -c "import redis_entraid; print('entraid_ok')" 2>/dev/null || echo "entraid_import_fail"
"$PY" -c "from genesis_cognitive.context.redis_client_factory import diagnose_redis_backends; print('factory_ok')" 2>/dev/null || echo "factory_import_fail"
"$PY" -c "from genesis_cognitive.brain.semantic_mode import get_semantic_mode; print('semantic_mode_ok')" 2>/dev/null || echo "semantic_import_fail"

echo "=== SERVICE ==="
systemctl is-active genesis-cognitive-8447
PID=$(systemctl show -p MainPID --value genesis-cognitive-8447)
echo "MainPID=$PID"
# presence only in process environ
tr '\0' '\n' < /proc/$PID/environ | grep -E '^(GENESIS_REDIS_AUTH_MODE|GENESIS_SESSION_BACKEND|GENESIS_REDIS_REQUIRED|GENESIS_SEMANTIC_MODE|GENESIS_ENV)=' | sed 's/=.*/=SET/' || echo ENV_KEYS_MISSING_IN_PROC
tr '\0' '\n' < /proc/$PID/environ | grep -E '^(GENESIS_REDIS_URL|GENESIS_CONV_LOCK_REDIS_URL)=' | sed 's/=.*/=SET/' || echo REDIS_URL_MISSING_IN_PROC

echo "=== HEALTH ==="
curl -sS --max-time 10 http://127.0.0.1:8447/health
echo

echo "=== READY_REDIS ==="
READY=$(curl -sS --max-time 20 -w '\nHTTP_CODE:%{http_code}\n' http://127.0.0.1:8447/ready/redis || true)
echo "$READY"

echo "=== OPS_PROBE ==="
# Load only Redis/V4 keys needed by factory — not a blind source of entire .env
export PYTHONPATH="$APP/src${PYTHONPATH:+:$PYTHONPATH}"
while IFS= read -r line; do
  case "$line" in
    GENESIS_REDIS_*|GENESIS_CONV_LOCK_*|GENESIS_SESSION_*|GENESIS_SNAPSHOT_*|GENESIS_ENV=*|GENESIS_SEMANTIC_MODE=*)
      key="${line%%=*}"
      val="${line#*=}"
      # strip surrounding quotes
      val="${val%\"}"; val="${val#\"}"
      val="${val%\'}"; val="${val#\'}"
      export "$key=$val"
      ;;
  esac
done < <(grep -E '^(GENESIS_REDIS_|GENESIS_CONV_LOCK_|GENESIS_SESSION_|GENESIS_SNAPSHOT_|GENESIS_ENV=|GENESIS_SEMANTIC_MODE=)' "$ENV" || true)

echo "PROBE_AUTH_MODE=${GENESIS_REDIS_AUTH_MODE:-unset}"
echo "PROBE_SESSION_BACKEND=${GENESIS_SESSION_BACKEND:-unset}"
"$PY" scripts/redis_entra_ops_probe.py --cas --lock --json || echo "PROBE_EXIT=$?"

echo "=== CONCURRENCY_HTTP ==="
BAR=/tmp/genesis-redis-barrier-$$
rm -rf "$BAR"
mkdir -p "$BAR"
# Service already uses Redis; harness only needs URL set as guard
export GENESIS_REDIS_URL="${GENESIS_REDIS_URL:-rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0}"
"$PY" tests/manual/redis_http_concurrency_harness.py --role A --barrier-dir "$BAR" --base-url http://127.0.0.1:8447 > /tmp/conc_A.json 2>/tmp/conc_A.err &
PA=$!
"$PY" tests/manual/redis_http_concurrency_harness.py --role B --barrier-dir "$BAR" --base-url http://127.0.0.1:8447 > /tmp/conc_B.json 2>/tmp/conc_B.err &
PB=$!
wait $PA; EA=$?
wait $PB; EB=$?
echo "ROLE_A_EXIT=$EA"
cat /tmp/conc_A.json 2>/dev/null || true
[ -s /tmp/conc_A.err ] && echo "ROLE_A_ERR=$(head -c 200 /tmp/conc_A.err)"
echo "ROLE_B_EXIT=$EB"
cat /tmp/conc_B.json 2>/dev/null || true
[ -s /tmp/conc_B.err ] && echo "ROLE_B_ERR=$(head -c 200 /tmp/conc_B.err)"
rm -rf "$BAR"

echo "DONE_VALIDATE"
