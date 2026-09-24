#!/bin/bash
# Validación Redis/Entra desde VM QA — sin secretos ni volcado de .env completo
set -u
echo "=== HOST ==="
hostname
echo "date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "user=$(whoami)"

echo "=== SERVICE ==="
systemctl is-active genesis-cognitive-8447 2>/dev/null || echo "service_inactive_or_missing"
PID=$(systemctl show -p MainPID --value genesis-cognitive-8447 2>/dev/null || echo 0)
echo "MainPID=$PID"
UNIT=$(systemctl show -p FragmentPath --value genesis-cognitive-8447 2>/dev/null || true)
echo "FragmentPath=$UNIT"
# EnvironmentFile paths only (no values)
if [ -n "$UNIT" ] && [ -f "$UNIT" ]; then
  grep -E '^EnvironmentFile=|^Environment=' "$UNIT" 2>/dev/null | sed 's/=.*/=SET_OR_PATH/' | head -20
  # drop-ins
  DROP=$(systemctl show -p DropInPaths --value genesis-cognitive-8447 2>/dev/null || true)
  echo "DropInPaths=${DROP:-none}"
fi

ENV_FILE=/opt/genesis-cognitive-8447/Genesis_v2/.env
echo "ENV_FILE_EXISTS=$([ -f "$ENV_FILE" ] && echo yes || echo no)"
if [ -f "$ENV_FILE" ]; then
  # Only presence of keys, never values
  for k in GENESIS_ENV GENESIS_REDIS_URL GENESIS_CONV_LOCK_REDIS_URL GENESIS_REDIS_AUTH_MODE \
           GENESIS_SESSION_BACKEND GENESIS_REDIS_REQUIRED GENESIS_SEMANTIC_MODE \
           GENESIS_AZURE_BRAIN GENESIS_AZURE_DEPLOYMENT GENESIS_HOST GENESIS_PORT; do
    if grep -qE "^${k}=" "$ENV_FILE" 2>/dev/null; then
      # redact value: show scheme/host/port hints for redis urls only
        if [ "$k" = "GENESIS_REDIS_URL" ] || [ "$k" = "GENESIS_CONV_LOCK_REDIS_URL" ]; then
          val=$(grep -E "^${k}=" "$ENV_FILE" | head -1 | cut -d= -f2-)
          safe=$(VAL="$val" python3 - <<'PY'
import os, urllib.parse
u=os.environ.get("VAL","").strip().strip('"').strip("'")
p=urllib.parse.urlparse(u)
host=p.hostname or ""
port=p.port or ""
print(f"{p.scheme}://{host}:{port}{p.path or ''}")
PY
)
          echo "${k}=PRESENT host_form=${safe}"
        else
          val=$(grep -E "^${k}=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
          echo "${k}=PRESENT value=${val}"
        fi
    else
      echo "${k}=ABSENT"
    fi
  done
fi

echo "=== CODE MARKERS ==="
APP=/opt/genesis-cognitive-8447/Genesis_v2
echo "APP_DIR_EXISTS=$([ -d "$APP" ] && echo yes || echo no)"
for f in \
  src/genesis_cognitive/context/redis_client_factory.py \
  src/genesis_cognitive/brain/azure_plan_turn.py \
  src/genesis_cognitive/brain/semantic_mode.py \
  scripts/redis_entra_ops_probe.py \
  deploy/corp-8447/redis_qa.env.example
 do
  if [ -f "$APP/$f" ]; then echo "HAS $f"; else echo "MISS $f"; fi
done
# deps in pyproject / venv
if [ -f "$APP/pyproject.toml" ]; then
  grep -E 'redis|redis-entraid' "$APP/pyproject.toml" | head -10 || true
fi
PY="$APP/.venv/bin/python"
echo "SERVICE_PYTHON=$([ -x "$PY" ] && echo "$PY" || echo missing)"
if [ -x "$PY" ]; then
  "$PY" -c "import redis; print('redis_ver', getattr(redis,'__version__','?'))" 2>/dev/null || echo "redis_import_fail"
  "$PY" -c "import redis_entraid; print('entraid_ok')" 2>/dev/null || echo "entraid_import_fail"
  "$PY" -c "from genesis_cognitive.context.redis_client_factory import create_redis_client; print('factory_ok')" 2>/dev/null || echo "factory_import_fail"
fi

echo "=== IDENTITY (IMDS) ==="
# System-assigned MI presence — oid only, no token
python3 - <<'PY'
import json, urllib.request, base64
try:
    req=urllib.request.Request(
        "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/",
        headers={"Metadata":"true"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        tok=json.load(resp)["access_token"]
    payload=tok.split(".")[1]+"=="
    claims=json.loads(base64.urlsafe_b64decode(payload))
    oid=claims.get("oid") or claims.get("appid")
    mirid=str(claims.get("xms_mirid",""))
    # truncate mirid to last segment
    print("IMDS_OK oid=", oid)
    print("IMDS_mirid_tail=", mirid[-90:] if mirid else "")
except Exception as e:
    print("IMDS_FAIL", type(e).__name__, str(e)[:120])
# Redis scope token length only
try:
    req=urllib.request.Request(
        "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://redis.azure.com/",
        headers={"Metadata":"true"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        tok=json.load(resp)["access_token"]
    print("REDIS_TOKEN_LEN", len(tok))
except Exception as e:
    print("REDIS_TOKEN_FAIL", type(e).__name__, str(e)[:120])
PY

echo "=== DNS / TCP ==="
HOST=bsc-cognitive-redis-qa.eastus.redis.azure.net
getent ahostsv4 "$HOST" 2>/dev/null | head -5 || true
python3 - <<'PY'
import socket
host="bsc-cognitive-redis-qa.eastus.redis.azure.net"
port=10000
try:
    infos=socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    ips=sorted({i[4][0] for i in infos})
    print("RESOLVED_IPS", ips)
    # private RFC1918?
    for ip in ips:
        parts=list(map(int, ip.split(".")))
        priv=(parts[0]==10) or (parts[0]==192 and parts[1]==168) or (parts[0]==172 and 16<=parts[1]<=31)
        print("IP", ip, "private" if priv else "PUBLIC_OR_OTHER")
    s=socket.create_connection((host, port), timeout=8)
    s.close()
    print("TCP_OK", host, port)
except Exception as e:
    print("TCP_FAIL", type(e).__name__, str(e)[:160])
PY

echo "=== LISTEN ==="
ss -lntp 2>/dev/null | grep -E ':8447|:8446' || netstat -lntp 2>/dev/null | grep -E ':8447|:8446' || echo "listen_probe_unavailable"

echo "=== HEALTH LOCAL ==="
curl -sS --max-time 8 http://127.0.0.1:8447/health || echo "health_fail"
echo
curl -sS --max-time 8 http://127.0.0.1:8447/ready/redis || echo "ready_redis_missing_or_fail"
echo
echo "=== DONE_DISCOVERY ==="
