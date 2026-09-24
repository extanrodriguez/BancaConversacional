#!/bin/bash
set -euo pipefail
echo "whoami=$(whoami)"
ls -la /opt/genesis-cognitive-8447/Genesis_v2/.env
test -w /opt/genesis-cognitive-8447/Genesis_v2/.env && echo ENV_WRITABLE=yes || echo ENV_WRITABLE=no
sudo -n true 2>/dev/null && echo SUDO_NOPASS=yes || echo SUDO_NOPASS=no
echo "=== redis mentions ==="
grep -RIl --include='*.env*' --include='*.yml' --include='*.json' \
  -e 'bsc-cognitive-redis' -e 'GENESIS_REDIS_URL' -e 'redis.azure.net' \
  /opt/genesis-cognitive-8447 /home/genesis 2>/dev/null | head -40 || true
echo "=== env redis keys ==="
grep -E '^(GENESIS_REDIS|REDIS|AZURE_REDIS)' /opt/genesis-cognitive-8447/Genesis_v2/.env 2>/dev/null \
  | sed -E 's/(=).*/\1SET/' || echo REDIS_ABSENT
echo "=== other env files ==="
find /opt/genesis-cognitive-8447 /opt/genesis-cognitive-8446 /home/genesis -name '.env' 2>/dev/null | head -20
while IFS= read -r f; do
  echo "FILE:$f"
  grep -E 'REDIS|redis\.azure' "$f" 2>/dev/null | sed -E 's/(=).*/\1SET/' | head -10 || true
done < <(find /opt/genesis-cognitive-8447 /opt/genesis-cognitive-8446 /home/genesis -name '.env' 2>/dev/null | head -20)

echo "=== keyvault probe via MI ==="
TOKEN=$(curl -sS --max-time 5 -H Metadata:true \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
SUB=f2119315-95df-4c68-9f83-fb12c2ee0dfa
curl -sS --max-time 30 -H "Authorization: Bearer ${TOKEN}" \
  "https://management.azure.com/subscriptions/${SUB}/resources?api-version=2021-04-01&\$top=200" \
  > /tmp/az_all_res.json || true
python3 - <<'PY'
import json
p="/tmp/az_all_res.json"
try:
  d=json.load(open(p))
except Exception as e:
  print("parse_fail", e); raise SystemExit
err=d.get("error") or {}
print("list_err", err.get("code"), (err.get("message") or "")[:160])
items=d.get("value") or []
print("count", len(items))
for i in items:
  t=i.get("type","")
  if any(x in t.lower() for x in ("keyvault","redis","cache","managedredis")):
    print(t, i.get("name"))
PY
