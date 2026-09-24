#!/bin/bash
# Merge selectivo Redis Entra + V4 semantic mode en .env 8447 (sin volcar secretos).
set -euo pipefail
ENV=/opt/genesis-cognitive-8447/Genesis_v2/.env
TS=$(date -u +%Y%m%d_%H%M%S)

if [[ ! -f "$ENV" ]]; then
  echo "ERROR: missing $ENV"
  exit 1
fi

cp -a "$ENV" "${ENV}.bak.entra.v4.${TS}"
echo "BACKUP=${ENV}.bak.entra.v4.${TS}"

_upsert() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV"
  fi
  echo "UPSERT_OK:${key}"
}

# Redis Entra (sin secretos) — valores de redis_qa.env.example
_upsert GENESIS_ENV qa
_upsert GENESIS_SESSION_BACKEND redis
_upsert GENESIS_REDIS_REQUIRED 1
_upsert GENESIS_REDIS_AUTH_MODE entra_managed_identity
_upsert GENESIS_REDIS_URL 'rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0'
_upsert GENESIS_CONV_LOCK_REDIS_URL 'rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0'
_upsert GENESIS_REDIS_ENTRA_RESOURCE 'https://redis.azure.com/'
_upsert GENESIS_SESSION_TTL_S 1800
_upsert GENESIS_CONV_LOCK_TTL_S 30
_upsert GENESIS_SNAPSHOT_TTL_S session

# V4 semantic (conserva Azure Brain existente)
_upsert GENESIS_SEMANTIC_MODE azure_plan

chmod 600 "$ENV"
chown genesis:genesis "$ENV" 2>/dev/null || true

# Presence-only confirmation (no dump)
for k in GENESIS_ENV GENESIS_SESSION_BACKEND GENESIS_REDIS_REQUIRED GENESIS_REDIS_AUTH_MODE \
         GENESIS_REDIS_URL GENESIS_CONV_LOCK_REDIS_URL GENESIS_SEMANTIC_MODE; do
  if grep -q "^${k}=" "$ENV"; then
    if [[ "$k" == *URL* ]]; then
      echo "${k}=PRESENT_HOST_FORM"
    else
      val=$(grep -E "^${k}=" "$ENV" | head -1 | cut -d= -f2-)
      echo "${k}=PRESENT value=${val}"
    fi
  else
    echo "${k}=ABSENT"
  fi
done

sudo systemctl restart genesis-cognitive-8447.service
sleep 4
systemctl is-active genesis-cognitive-8447.service
echo "=== HEALTH ==="
curl -sS --max-time 10 http://127.0.0.1:8447/health || true
echo
echo "=== READY_REDIS ==="
curl -sS --max-time 15 http://127.0.0.1:8447/ready/redis || true
echo
echo "DONE_MERGE"
