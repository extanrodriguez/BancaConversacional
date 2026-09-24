#!/bin/bash
# Probe Entra ID auth to Azure Managed Redis using VM managed identity.
set -euo pipefail
HOST=bsc-cognitive-redis-qa.eastus.redis.azure.net
PORT=10000
OID=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
  | python3 -c "import sys,json,base64; t=json.load(sys.stdin)['access_token']; p=t.split('.')[1]+'=='; import json as J; print(J.loads(base64.urlsafe_b64decode(p)).get('oid') or J.loads(base64.urlsafe_b64decode(p)).get('appid'))")
echo "MI_OID_OR_APP=$OID"
# Token for Redis scope
RTOKEN=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://redis.azure.com/" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token','')[:12]+'...LEN'+str(len(json.load(open('/dev/stdin')))) )" 2>/dev/null || true)

# cleaner token fetch (venv has redis package)
/opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python - <<'PY'
import json, urllib.request, ssl, socket
import redis

def imds(resource: str) -> str:
    req = urllib.request.Request(
        f"http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource={resource}",
        headers={"Metadata": "true"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.load(resp)["access_token"]

# decode oid
import base64
mgmt = imds("https://management.azure.com/")
payload = mgmt.split(".")[1] + "=="
claims = json.loads(base64.urlsafe_b64decode(payload))
oid = claims.get("oid") or claims.get("appid")
print("claims_oid", oid)
print("claims_xms_mirid", str(claims.get("xms_mirid", ""))[-80:])

token = imds("https://redis.azure.com")
print("redis_token_len", len(token))

host = "bsc-cognitive-redis-qa.eastus.redis.azure.net"
port = 10000

# TCP reachability
try:
    s = socket.create_connection((host, port), timeout=5)
    s.close()
    print("TCP_OK", host, port)
except Exception as e:
    print("TCP_FAIL", type(e).__name__, str(e)[:120])

# Try redis-py with Entra (username=oid, password=token, ssl)
try:
    c = redis.Redis(
        host=host,
        port=port,
        username=oid,
        password=token,
        ssl=True,
        ssl_cert_reqs=None,
        decode_responses=True,
        socket_connect_timeout=8,
        socket_timeout=8,
    )
    print("ENTRA_PING", c.ping())
except Exception as e:
    print("ENTRA_FAIL", type(e).__name__, str(e)[:200])

# Also try empty password / default user (should fail)
try:
    c2 = redis.Redis(host=host, port=port, ssl=True, ssl_cert_reqs=None, socket_connect_timeout=5)
    print("ANON_PING", c2.ping())
except Exception as e:
    print("ANON_FAIL", type(e).__name__, str(e)[:120])
PY
