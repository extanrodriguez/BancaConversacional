#!/bin/bash
# Cablea GENESIS_REDIS_URL en .env 8447. Lee key desde /tmp/redis_primary.key
set -euo pipefail
KEY_FILE=/tmp/redis_primary.key
ENV=/opt/genesis-cognitive-8447/Genesis_v2/.env
HOST=bsc-cognitive-redis-qa.eastus.redis.azure.net
PORT=10000
PY=/opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python

if [[ ! -f "$KEY_FILE" ]]; then
  echo "ERROR: missing $KEY_FILE"
  exit 1
fi
KEY=$(tr -d '\r\n' < "$KEY_FILE")
if [[ ${#KEY} -lt 8 ]]; then
  echo "ERROR: key too short"
  exit 1
fi

# URL-encode key via python
URL=$("$PY" - <<PY
from urllib.parse import quote
key=open("$KEY_FILE","rb").read().decode().strip()
print(f"rediss://:{quote(key, safe='')}@$HOST:$PORT/0")
PY
)

TS=$(date -u +%Y%m%d_%H%M%S)
cp -a "$ENV" "${ENV}.bak.redis.${TS}"
grep -v -E '^(GENESIS_REDIS_URL|GENESIS_CONV_LOCK_REDIS_URL)=' "$ENV" > "${ENV}.tmp" || true
mv "${ENV}.tmp" "$ENV"
printf 'GENESIS_REDIS_URL=%s\n' "$URL" >> "$ENV"
printf 'GENESIS_CONV_LOCK_REDIS_URL=%s\n' "$URL" >> "$ENV"
chmod 600 "$ENV"

# presence checks
grep -q '^GENESIS_REDIS_URL=rediss://' "$ENV" && echo UPSERT_OK:GENESIS_REDIS_URL
grep -q '^GENESIS_CONV_LOCK_REDIS_URL=rediss://' "$ENV" && echo UPSERT_OK:GENESIS_CONV_LOCK_REDIS_URL
echo "BACKUP=${ENV}.bak.redis.${TS}"

# Ping
export URL
"$PY" - <<'PY'
import os, redis
url=os.environ["URL"]
c=redis.from_url(url, decode_responses=True, socket_connect_timeout=8, socket_timeout=8)
print("PING", c.ping())
print("ENDPOINT", url.split("@",1)[-1])
PY

# Restart service
sudo systemctl restart genesis-cognitive-8447.service
sleep 3
systemctl is-active genesis-cognitive-8447.service
curl -sS --max-time 8 http://127.0.0.1:8447/health
echo
# Confirm env in process (presence only)
PID=$(systemctl show -p MainPID --value genesis-cognitive-8447)
tr '\0' '\n' < /proc/$PID/environ | grep -E '^GENESIS_REDIS_URL=|^GENESIS_CONV_LOCK_REDIS_URL=' | sed 's/=.*/=SET/' || echo ENV_IN_PROC_MISSING

# scrub key file
shred -u "$KEY_FILE" 2>/dev/null || rm -f "$KEY_FILE"
echo DONE
