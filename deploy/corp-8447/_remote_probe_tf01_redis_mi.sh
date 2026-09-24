#!/bin/bash
set -euo pipefail
echo "HOST=$(hostname)"
curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/instance/compute?api-version=2021-02-01" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print("vmName", d.get("name")); print("resourceId_tail", (d.get("resourceId") or "")[-90:])'

TOK=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/")
echo "$TOK" | python3 -c '
import sys,json,base64
d=json.load(sys.stdin)
t=d.get("access_token","")
print("MGMT_TOKEN_LEN", len(t))
if not t:
    print("MGMT_TOKEN_ERR", d); raise SystemExit(0)
p=t.split(".")[1] + "=="
c=json.loads(base64.urlsafe_b64decode(p))
print("OID", c.get("oid"))
print("APPID", c.get("appid"))
print("TID", (c.get("tid") or "")[:12])
'

RTOK=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://redis.azure.com/")
echo "$RTOK" | python3 -c '
import sys,json
d=json.load(sys.stdin)
t=d.get("access_token","")
print("REDIS_TOKEN_LEN", len(t))
if not t:
    print("REDIS_TOKEN_ERR", d)
'

getent hosts bsc-cognitive-redis-qa.eastus.redis.azure.net || echo DNS_FAIL
timeout 3 bash -c '</dev/tcp/192.168.150.7/10000' && echo REDIS_TCP_OK || echo REDIS_TCP_FAIL

echo "=== env markers ==="
grep -E '^(GENESIS_ENV|GENESIS_SESSION_BACKEND|GENESIS_REDIS_REQUIRED|GENESIS_REDIS_AUTH_MODE|GENESIS_SEMANTIC_MODE)=' \
  /opt/genesis-cognitive-8447/Genesis_v2/.env || true

if [ -x /opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python ]; then
  cd /opt/genesis-cognitive-8447/Genesis_v2
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^#' .env | sed '/^\s*$/d')
  set +a
  .venv/bin/python - <<'PY'
import os
try:
    from genesis_cognitive.context.redis_client_factory import create_and_ping
    c = create_and_ping()
    print("CREATE_AND_PING", bool(c))
except Exception as e:
    print("CREATE_AND_PING_FAIL", type(e).__name__, str(e)[:300])
PY
fi
