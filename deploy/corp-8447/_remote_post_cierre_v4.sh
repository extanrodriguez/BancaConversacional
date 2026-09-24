#!/bin/bash
# Post-deploy: ensure Redis Entra + azure_plan still present; verify markers; ready/redis
set -euo pipefail
APP=/opt/genesis-cognitive-8447/Genesis_v2
ENV=$APP/.env
PY=$APP/.venv/bin/python

_upsert() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV"
  fi
}

# Conservar/reassegurar config (deploy preserva .env pero reafirma claves)
_upsert GENESIS_ENV qa
_upsert GENESIS_SESSION_BACKEND redis
_upsert GENESIS_REDIS_REQUIRED 1
_upsert GENESIS_REDIS_AUTH_MODE entra_managed_identity
_upsert GENESIS_REDIS_URL 'rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0'
_upsert GENESIS_CONV_LOCK_REDIS_URL 'rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0'
_upsert GENESIS_SEMANTIC_MODE azure_plan
_upsert GENESIS_REDIS_ENTRA_RESOURCE 'https://redis.azure.com/'
chmod 600 "$ENV"

# Kill stuck then restart (evita stop-sigterm timeout)
sudo systemctl kill -s SIGKILL genesis-cognitive-8447.service 2>/dev/null || true
sudo systemctl reset-failed genesis-cognitive-8447.service 2>/dev/null || true
sudo systemctl start genesis-cognitive-8447.service
sleep 6
systemctl is-active genesis-cognitive-8447

echo "=== MARKERS ==="
test -f $APP/src/genesis_cognitive/brain/azure_plan_adapter.py && echo OK_adapter
grep -n 'lifespan\|_to_thread\|_warm_gate\|turn_handler_isolate\|plan_from_pending_selection' \
  $APP/src/genesis_cognitive/demo/contract_inspector_app.py \
  $APP/src/genesis_cognitive/brain/azure_plan_turn.py \
  $APP/src/genesis_cognitive/brain/azure_plan_adapter.py 2>/dev/null | head -20 || true

echo "=== HEALTH ==="
curl -sS -m 8 http://127.0.0.1:8447/health; echo
echo "=== READY_REDIS ==="
curl -sS -m 12 http://127.0.0.1:8447/ready/redis; echo
echo "DONE_POST"
